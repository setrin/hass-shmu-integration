"""Read public SHMÚ products with bounded retries and an in-memory run cache."""

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import aiohttp

from .const import DATA_URL, MAX_RUN_AGE_HOURS, PRODUCTS_URL, STATIONS_URL
from .forecast import LOCAL_TZ, ModelRun, merge_runs, parse_run


class ShmuError(Exception):
    """SHMÚ data could not be retrieved or validated."""


@dataclass
class ForecastData:
    """Usable forecast plus source health metadata."""

    runs: dict[str, ModelRun]
    hours: dict[int, dict]
    degraded_models: list[str]


class ShmuClient:
    """One client per configured city; session lifetime belongs to Home Assistant."""

    def __init__(self, session, station_id):
        self.session = session
        self.station_id = str(station_id)
        if not self.station_id.isdigit():
            raise ValueError("Invalid station ID")
        self._cache = {}
        self._history = {}

    async def _json(self, url):
        try:
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as response:
                response.raise_for_status()
                return await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise ShmuError(f"Unable to read {url}: {err}") from err

    async def stations(self):
        data = await self._json(STATIONS_URL)
        try:
            if not isinstance(data, list) or not data:
                raise ValueError("Empty station list")
            return {
                str(row["station_id"]): {
                    "station_id": str(row["station_id"]),
                    "name": str(row["station_name"]),
                    "latitude": float(row["lat"]),
                    "longitude": float(row["lon"]),
                }
                for row in data
                if str(row["station_id"]).isdigit()
            }
        except (KeyError, TypeError, ValueError) as err:
            raise ShmuError("Invalid station list") from err

    def _fallback_paths(self, model, now):
        step = 6 if model == "aladin" else 12
        run = now.replace(hour=(now.hour // step) * step, minute=0, second=0, microsecond=0)
        # Most recent four candidate cycles; this is used only if the index fails.
        return [
            f"{model}/{dt:%Y-%m-%d}/{self.station_id}_{dt:%Y-%m-%d_%H}.json"
            for dt in (run - timedelta(hours=step * i) for i in range(4))
        ]

    async def _model(self, model, paths, now):
        cached = self._cache.get(model)
        hour = int(now.timestamp()) // 3600 * 3600

        def usable(run):
            return (
                timedelta(0) <= now - run.initialized <= timedelta(hours=MAX_RUN_AGE_HOURS)
                and hour in run.hours
            )

        for index, path in enumerate(paths[:4]):
            if cached and cached[0] == path and usable(cached[1]):
                return cached[1], index > 0
            try:
                payload = await self._json(f"{DATA_URL}/{path}")
                run = parse_run(payload, model, self.station_id)
                expected = f"{model}/{run.initialized:%Y-%m-%d}/{self.station_id}_"
                expected += f"{run.initialized:%Y-%m-%d_%H}.json"
                if path != expected or not usable(run):
                    raise ValueError("Run identity mismatch or expired forecast")
            except (ShmuError, KeyError, TypeError, ValueError, IndexError, OverflowError):
                continue
            self._cache[model] = (path, run)
            return run, index > 0
        if cached and usable(cached[1]):
            return cached[1], True
        return None, True

    async def _today_hours(self, model, run, paths, now):
        """Recover elapsed hours after restart without replacing current/future values."""
        midnight = now.astimezone(LOCAL_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        start = int(midnight.timestamp())
        hour = int(now.timestamp()) // 3600 * 3600
        history = {t: row for t, row in self._history.get(model, {}).items() if start <= t < hour}
        hours = history | run.hours
        missing = set(range(start, hour, 3600)) - hours.keys()
        if missing:
            # Use published entries and predictable preceding cycles, newest first.
            step = 6 if model == "aladin" else 12
            candidates = list(paths) + [
                f"{model}/{dt:%Y-%m-%d}/{self.station_id}_{dt:%Y-%m-%d_%H}.json"
                for dt in (run.initialized - timedelta(hours=step * i) for i in range(1, 5))
            ]
            older = []
            for path in dict.fromkeys(candidates):
                try:
                    stamp = (
                        path.rsplit("/", 1)[-1]
                        .removeprefix(f"{self.station_id}_")
                        .removesuffix(".json")
                    )
                    initialized = datetime.strptime(stamp, "%Y-%m-%d_%H").replace(tzinfo=UTC)
                except ValueError:
                    continue
                if initialized < run.initialized and timedelta(0) <= now - initialized <= timedelta(
                    hours=MAX_RUN_AGE_HOURS
                ):
                    older.append((initialized, path))
            for initialized, path in sorted(older, reverse=True)[:4]:
                try:
                    previous = parse_run(
                        await self._json(f"{DATA_URL}/{path}"), model, self.station_id
                    )
                    if previous.initialized != initialized:
                        raise ValueError("Historical run identity mismatch")
                except (ShmuError, KeyError, TypeError, ValueError, IndexError, OverflowError):
                    continue
                hours.update({t: previous.hours[t] for t in missing if t in previous.hours})
                missing -= hours.keys()
                if not missing:
                    break
        # At most one local day's records per model, including hours that will elapse
        # before the next refresh. Keep latest-run metadata separate from older hours.
        self._history[model] = {
            t: row
            for t, row in hours.items()
            if datetime.fromtimestamp(t, UTC).astimezone(LOCAL_TZ).date() == midnight.date()
        }
        return ModelRun(model, run.initialized, hours)

    async def fetch(self, mode, now=None):
        now = (now or datetime.now(UTC)).astimezone(UTC)
        models = ("aladin", "ecmwf") if mode == "combined" else (mode,)
        if any(model not in ("aladin", "ecmwf") for model in models):
            raise ShmuError("Invalid model selection")
        index_failed = False
        try:
            products = await self._json(f"{PRODUCTS_URL}?station={self.station_id}")
            if str(products["station"]["station_id"]) != self.station_id:
                raise ValueError("Station index mismatch")
            rows = sorted(products["data"], key=lambda row: int(row["runtime"]), reverse=True)
        except (ShmuError, KeyError, TypeError, ValueError):
            index_failed = True
            rows = []
        paths_by_model = {}
        for model in models:
            # Accept only same-station relative paths on the fixed SHMÚ host.
            pattern = (
                rf"{model}/\d{{4}}-\d{{2}}-\d{{2}}/{self.station_id}_"
                r"\d{4}-\d{2}-\d{2}_\d{2}\.json"
            )
            paths = [
                row["file_link"]
                for row in rows
                if row.get("type") == model
                and re.fullmatch(pattern, str(row.get("file_link", "")))
                and int(row["runtime"]) <= now.timestamp()
            ]
            paths_by_model[model] = list(dict.fromkeys(paths)) or self._fallback_paths(model, now)
        results = await asyncio.gather(
            *(self._model(model, paths_by_model[model], now) for model in models)
        )
        runs = {model: run for model, (run, _) in zip(models, results, strict=True) if run}
        hours = merge_runs(runs, mode)
        if int(now.timestamp()) // 3600 * 3600 not in hours:
            raise ShmuError("No fresh forecast covers the current hour")
        historical = await asyncio.gather(
            *(
                self._today_hours(model, run, paths_by_model[model], now)
                for model, run in runs.items()
            )
        )
        hours = merge_runs({run.model: run for run in historical}, mode)
        degraded = [
            model
            for model, (_, fallback) in zip(models, results, strict=True)
            if fallback or index_failed
        ]
        return ForecastData(runs, hours, degraded)
