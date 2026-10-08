"""Optional measured weather and current district warnings from SHMÚ.

Observation clocks are fixed CET (UTC+1), per the provider's metadata.
Warnings use the website's civil Slovak time and include upcoming warnings.
The currently stale open-data CAP directory is deliberately not used.
"""

import asyncio
import json
import math
import re
from datetime import UTC, datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import aiohttp

from .api import ShmuError
from .stations import get_station, nearest_station
from .tls import observation_ssl_context

OBS_URL = "https://opendata.shmu.sk/meteorology/climate/now/data/"
MAP_URL = "https://www.shmu.sk/assets/maps/meteo_map.json"
WARNING_URL = "https://www.shmu.sk/popups/meteo/vystrahy.php?region={}&page=987"
CET = timezone(timedelta(hours=1))
LOCAL = ZoneInfo("Europe/Bratislava")
MAX_OBSERVATION_AGE = timedelta(minutes=30)


class PlainText(HTMLParser):
    """Extract text without evaluating scripts or retaining markup."""

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.feed(source)

    def handle_data(self, data):
        self.parts.append(data)

    @property
    def text(self):
        return " ".join(" ".join(self.parts).split())


def _number(value, low, high):
    if isinstance(value, bool) or value is None:
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and low <= value <= high else None
    except (TypeError, ValueError):
        return None


def parse_observation(payload, station, now):
    """Newest valid reading of the selected station, with a strict age limit."""
    rows = []
    for row in payload["data"]:
        if str(row.get("ind_kli")) != str(station.ind_kli):
            continue
        try:
            measured = datetime.fromisoformat(row["minuta"])
            if measured.tzinfo is None:
                measured = measured.replace(tzinfo=CET)
            measured = measured.astimezone(UTC)
            if not -timedelta(minutes=2) <= now - measured <= MAX_OBSERVATION_AGE:
                continue
            temperature = _number(row.get("t"), -80, 60)
            if temperature is not None:
                rows.append((measured, row, temperature))
        except (TypeError, ValueError, KeyError):
            continue
    if not rows:
        raise ShmuError("No fresh observation for selected station")
    measured, row, temperature = max(rows, key=lambda item: item[0])
    result = {"native_temperature": temperature, "measured_at": measured.isoformat()}
    for source, target, low, high in (
        ("vlh_rel", "humidity", 0, 100),
        ("vie_pr_rych", "native_wind_speed", 0, 150),
        ("vie_max_rych", "native_wind_gust_speed", 0, 150),
        ("vie_pr_smer", "wind_bearing", 0, 360),
        ("dohl", "native_visibility", 0, 100000),
    ):
        value = _number(row.get(source), low, high)
        if value is not None:
            result[target] = value / 1000 if target == "native_visibility" else value
    # Station pressure is not sea-level pressure. Reduce it before exposing it.
    pressure = _number(row.get("tlak"), 400, 1100)
    if pressure is not None:
        ratio = 1 - 0.0065 * station.elevation / (temperature + 273.15 + 0.0065 * station.elevation)
        result["native_pressure"] = round(pressure * ratio**-5.255, 1)
    return result


def _inside_ring(x, y, ring):
    inside = False
    for a, b in zip(ring, ring[1:] + ring[:1], strict=True):
        x1, y1 = a[:2]
        x2, y2 = b[:2]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def district_for_point(geojson, latitude, longitude):
    """Resolve the city's district using SHMÚ's own warning map boundaries."""
    for feature in geojson["features"]:
        geometry = feature["geometry"]
        polygons = geometry["coordinates"]
        if geometry["type"] == "Polygon":
            polygons = [polygons]
        elif geometry["type"] != "MultiPolygon":
            continue
        for rings in polygons:
            if _inside_ring(longitude, latitude, rings[0]) and not any(
                _inside_ring(longitude, latitude, hole) for hole in rings[1:]
            ):
                props = feature["properties"]
                code = props["SKRATKA"]
                if re.fullmatch(r"[A-Z]{2}", code):
                    return {"code": code, "name": props["NAZOV_OKRE"]}
    raise ShmuError("City is outside the SHMÚ warning map")


def parse_warnings(source, district, now):
    """Parse the current public district detail; fail closed on layout changes."""
    caption = re.search(r"<caption\b[^>]*>(.*?)</caption>", source, re.S | re.I)
    if not caption or PlainText(caption[1]).text != (
        f"Meteorologické výstrahy pre okres {district['name']}"
    ):
        raise ShmuError("Warning district page did not match")
    body = re.search(r"<tbody\b[^>]*>(.*?)</tbody>", source, re.S | re.I)
    if not body:
        raise ShmuError("Warning table missing")
    blocks = re.split(r'<td\s+class="warn_([123])"[^>]*>', source[caption.end() :])
    if len(blocks) == 1 and (PlainText(body[1]).text or re.search(r"<t[rd]\b", body[1])):
        raise ShmuError("Unrecognized warning table")
    alerts = []
    for level, block in zip(blocks[1::2], blocks[2::2], strict=True):
        # Public-health advice has its own nested tables; only the warning precedes it.
        block = re.sub(r"^.*?</td>", "", block, count=1, flags=re.S)
        text = PlainText(re.split(r'<div id="(?:uvz|mv)-texty"|</td>', block)[0]).text
        if f"Stupeň: {level}. stupeň" not in text:
            raise ShmuError("Warning severity mismatch")
        match = re.search(
            r"Jav: (.+?) Stupeň: [123]\. stupeň Trvanie javu: od "
            r"(\d{1,2}\.\d{1,2}\.\d{4} \d{2}:\d{2}) do "
            r"(\d{1,2}\.\d{1,2}\.\d{4} \d{2}:\d{2}) Výstraha: (.+)",
            text,
        )
        if not match:
            raise ShmuError("Unrecognized warning details")
        start, end = (
            datetime.strptime(value, "%d.%m.%Y %H:%M").replace(tzinfo=LOCAL).astimezone(UTC)
            for value in (match[2], match[3])
        )
        if end <= start:
            raise ShmuError("Invalid warning period")
        if end > now:
            alert = {
                "event": match[1],
                "level": int(level),
                "starts_at": start.isoformat(),
                "ends_at": end.isoformat(),
                "description": match[4],
            }
            if alert not in alerts:
                alerts.append(alert)
    return {
        "district": district["name"],
        "url": WARNING_URL.format(district["code"]),
        "checked_at": now.isoformat(),
        "alerts": alerts,
    }


class LiveClient:
    """Independent optional sources; neither failure suppresses the forecast."""

    def __init__(self, session, latitude, longitude, station_id="auto"):
        self.session = session
        self.latitude = latitude
        self.longitude = longitude
        self.station = (
            nearest_station(latitude, longitude)
            if station_id in ("auto", "model")
            else get_station(int(station_id))
        )
        if self.station is None:
            raise ValueError("Unknown observation station")
        self.model_only = station_id == "model"
        self.district = None
        self._ssl_context = None

    async def _text(self, url):
        try:
            kwargs = {}
            if url.startswith(OBS_URL):
                if self._ssl_context is None:
                    self._ssl_context = await asyncio.to_thread(observation_ssl_context)
                kwargs["ssl"] = self._ssl_context
            async with self.session.get(
                url, timeout=aiohttp.ClientTimeout(total=20), **kwargs
            ) as response:
                response.raise_for_status()
                return await response.text()
        except (aiohttp.ClientError, TimeoutError, UnicodeError) as err:
            raise ShmuError("SHMÚ live source unavailable") from err

    async def observations(self, now):
        if self.model_only:
            return None
        # Follow only validated relative paths, never arbitrary links from HTML.
        index = await self._text(OBS_URL)
        days = sorted(set(re.findall(r'href="(\d{8})/"', index)), reverse=True)[:2]
        for day in days:
            listing = await self._text(f"{OBS_URL}{day}/")
            files = sorted(
                {
                    unquote(link)
                    for link in re.findall(r'href="([^"/]+)"', listing)
                    if re.fullmatch(
                        r"aws1min - \d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}\.json", unquote(link)
                    )
                },
                reverse=True,
            )
            for filename in files[:3]:
                try:
                    data = json.loads(await self._text(f"{OBS_URL}{day}/{filename}"))
                    result = parse_observation(data, self.station, now)
                    return result | {
                        "station": self.station.name,
                        "station_id": self.station.ind_kli,
                        "distance_km": round(
                            self.station.distance_km(self.latitude, self.longitude), 1
                        ),
                    }
                except (ShmuError, ValueError, KeyError, TypeError):
                    continue
        raise ShmuError("No fresh observation available")

    async def warnings(self, now):
        if self.district is None:
            self.district = district_for_point(
                json.loads(await self._text(MAP_URL)), self.latitude, self.longitude
            )
        source = await self._text(WARNING_URL.format(self.district["code"]))
        return parse_warnings(source, self.district, now)

    async def fetch(self, now=None):
        now = now or datetime.now(UTC)

        async def bounded(method):
            async with asyncio.timeout(45):
                return await method(now)

        values = await asyncio.gather(
            bounded(self.observations), bounded(self.warnings), return_exceptions=True
        )
        return {
            key: None if isinstance(value, Exception) else value
            for key, value in zip(("observation", "warnings"), values, strict=True)
        }
