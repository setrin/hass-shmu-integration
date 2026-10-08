"""SHMÚ series normalization; independent of Home Assistant and network I/O.

Hourly timestamps mark the START of the forecast hour. Instantaneous fields are
interpolated, while precipitation is allocated from intervals ending at source
timestamps. No extrapolation beyond a model's temperature coverage is allowed.
"""

from bisect import bisect_left
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

FIELDS = {
    "native_temperature": ("Air_temperature_at_2m", "°C"),
    "native_pressure": ("Mean_sea_level_pressure", "hPa"),
    "native_wind_speed": ("Wind_speed_at_10m", "m/s"),
    "native_wind_gust_speed": ("Wind_gust_at_10m", "m/s"),
    "cloud_coverage": ("Total_cloud_cover", "%"),
    "native_precipitation": ("Total_precipitation", "mm"),
    "snowfall": ("Snowfall", "mm"),
    "wind_bearing": ("Wind_direction_at_10m", None),
}
LOCAL_TZ = ZoneInfo("Europe/Bratislava")


def number(value):
    """Keep missing/non-finite data missing, not zero."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
        return float(value)
    return None


def series(payload, key, unit=None):
    """Decode deterministic values, ensemble medians, or modal wind sectors."""
    field = payload.get(key)
    if field is None:
        return {}
    if not isinstance(field, dict) or (unit and field.get("unit") != unit):
        raise ValueError(f"Invalid field or unit: {key}")
    columns = field.get("columns")
    direction = key == "Wind_direction_at_10m" and columns is not None
    if columns is not None and not direction and "Median" not in columns:
        raise ValueError(f"Missing ensemble median: {key}")
    index = columns.index("Median") if columns and not direction else 1
    result = {}
    for row in field.get("data", []):
        if not isinstance(row, list) or len(row) <= index or number(row[0]) is None:
            raise ValueError(f"Invalid data row: {key}")
        value = number(row[index])
        if direction:
            sectors = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
            counts = [number(row[columns.index(s)]) for s in sectors]
            if all(c is not None and c >= 0 for c in counts) and max(counts) > 0:
                # Dominant member direction; never interpret counts as degrees.
                value = float(counts.index(max(counts)) * 45)
            else:
                value = None
        result[int(row[0])] = value
    return dict(sorted(result.items()))


def interpolate(values, timestamp, circular=False):
    """Interpolate across at most six hours; never bridge explicit missing values."""
    times = list(values)
    i = bisect_left(times, timestamp)
    if i < len(times) and times[i] == timestamp:
        return values[times[i]]
    if i == 0 or i == len(times):
        return None
    left, right = times[i - 1], times[i]
    a, b = values[left], values[right]
    if a is None or b is None or right - left > 21600:
        return None
    delta = (b - a + 180) % 360 - 180 if circular else b - a
    value = a + delta * (timestamp - left) / (right - left)
    return value % 360 if circular else value


def interval_amount(values, start, hours):
    """Allocate an interval total uniformly to one hour without double counting."""
    end = start + 3600
    matches = [(t, v) for t, v in values.items() if t >= end and t - hours * 3600 <= start]
    if len(matches) != 1 or matches[0][1] is None:
        return None
    return max(0, matches[0][1]) / hours


@dataclass(frozen=True)
class ModelRun:
    """A validated run and normalized hourly records."""

    model: str
    initialized: datetime
    hours: dict[int, dict]


def parse_run(payload, model, station_id):
    """Validate identity and decode a run using field timestamps, never row positions."""
    if model not in ("aladin", "ecmwf") or not isinstance(payload, dict):
        raise ValueError("Invalid model payload")
    if str(payload.get("si_id")) != str(station_id):
        raise ValueError("Station mismatch")
    if not str(payload.get("model_name", "")).upper().startswith(model.upper()):
        raise ValueError("Model mismatch")
    initialized = datetime.fromisoformat(payload["data_date_time"].replace("Z", "+00:00"))
    if initialized.tzinfo is None:
        raise ValueError("Run time must include UTC offset")
    data = {name: series(payload, key, unit) for name, (key, unit) in FIELDS.items()}
    temps = data["native_temperature"]
    valid = [t for t, v in temps.items() if v is not None]
    if len(valid) < 2:
        raise ValueError("Missing temperature forecast")
    if valid[-1] - valid[0] > 15 * 86400:
        raise ValueError("Unreasonable forecast horizon")
    hours = {}
    for t in range(((valid[0] + 3599) // 3600) * 3600, valid[-1], 3600):
        record = {"datetime": datetime.fromtimestamp(t, UTC).isoformat(), "model": model}
        for name, values in data.items():
            if name in ("native_precipitation", "snowfall"):
                value = interval_amount(values, t, 1 if model == "aladin" else 6)
            else:
                value = interpolate(values, t, circular=name == "wind_bearing")
            if value is not None:
                record[name] = round(value, 4)
        if "native_temperature" in record:
            hours[t] = record
    if not hours:
        raise ValueError("No usable hours")
    return ModelRun(model, initialized.astimezone(UTC), hours)


def merge_runs(runs, mode):
    """Prefer ALADIN for every available hour, then fill/extend with ECMWF."""
    if mode not in ("combined", "aladin", "ecmwf"):
        raise ValueError("Invalid forecast mode")
    models = ("ecmwf", "aladin") if mode == "combined" else (mode,)
    merged = {}
    for model in models:
        if model in runs:
            merged.update(runs[model].hours)
    return dict(sorted(merged.items()))


def condition(record, is_day=True):
    """Conservative heuristic: source has no official condition codes."""
    rain = record.get("native_precipitation")
    snow = record.get("snowfall")
    if snow is not None and snow >= 0.1:
        return "snowy-rainy" if rain is not None and rain - snow >= 0.1 else "snowy"
    if rain is not None and rain >= 0.1:
        return "pouring" if rain >= 4 else "rainy"
    cloud = record.get("cloud_coverage")
    if cloud is None:
        return None
    if cloud >= 80:
        return "cloudy"
    if cloud >= 20:
        return "partlycloudy"
    return "sunny" if is_day else "clear-night"


def daily_forecasts(hours, now):
    """Aggregate modeled hours by Slovak calendar day (including 23/25-hour DST days).

    Today includes past modeled hours where available. Incomplete future days are omitted.
    Temperature extrema are extrema of sampled/interpolated temperatures, not
    ensemble minimum/maximum members or SHMÚ interval-extreme fields.
    """
    grouped = {}
    today = now.astimezone(LOCAL_TZ).date()
    for timestamp, record in hours.items():
        day = datetime.fromtimestamp(timestamp, UTC).astimezone(LOCAL_TZ).date()
        if day >= today:
            grouped.setdefault(day, []).append(record)
    result = []
    for day, records in sorted(grouped.items()):
        midnight = datetime.combine(day, datetime.min.time(), LOCAL_TZ)
        end = datetime.combine(day + timedelta(days=1), datetime.min.time(), LOCAL_TZ)
        expected = int((end.astimezone(UTC) - midnight.astimezone(UTC)).total_seconds() / 3600)
        if day > today and len(records) != expected:
            continue
        item = {
            "datetime": midnight.astimezone(UTC).isoformat(),
            "native_temperature": max(r["native_temperature"] for r in records),
            "native_templow": min(r["native_temperature"] for r in records),
        }
        for field in ("native_precipitation", "snowfall"):
            if all(field in r for r in records):
                item[field] = round(sum(r[field] for r in records), 3)
        clouds = [r["cloud_coverage"] for r in records if "cloud_coverage" in r]
        if clouds:
            item["cloud_coverage"] = round(sum(clouds) / len(clouds))
        for field in ("native_wind_speed", "native_wind_gust_speed"):
            values = [r[field] for r in records if field in r]
            if values:
                item[field] = max(values)
        # A wet hour must remain visible even when the rest of the day is dry.
        wet_priority = ("snowy-rainy", "snowy", "pouring", "rainy")
        icons = {condition(record) for record in records}
        icon = next((value for value in wet_priority if value in icons), condition(item))
        if icon:
            item["condition"] = icon
        item.pop("snowfall", None)
        result.append(item)
    return result


def day_coverage(hours, now):
    """Expose partial-day coverage separately from Home Assistant forecast fields."""
    counts = {}
    for t in hours:
        day = datetime.fromtimestamp(t, UTC).astimezone(LOCAL_TZ).date()
        if day >= now.astimezone(LOCAL_TZ).date():
            counts[day] = counts.get(day, 0) + 1
    result = {}
    for day, count in sorted(counts.items()):
        a = datetime.combine(day, datetime.min.time(), LOCAL_TZ).astimezone(UTC)
        b = datetime.combine(day + timedelta(days=1), datetime.min.time(), LOCAL_TZ).astimezone(UTC)
        result[day.isoformat()] = {
            "hours": count,
            "expected_hours": int((b - a).total_seconds() / 3600),
        }
    return result
