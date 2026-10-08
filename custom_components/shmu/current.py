"""Shared current-weather source selection for weather and sensor entities."""

from datetime import UTC, datetime

from .live import MAX_OBSERVATION_AGE


def fresh_observation(coordinator, now):
    live = coordinator.live
    row = (live.data or {}).get("observation") if live.last_update_success else None
    if row and now - datetime.fromisoformat(row["measured_at"]) <= MAX_OBSERVATION_AGE:
        return row
    return None


def current_forecast(coordinator, now):
    timestamp = int(now.astimezone(UTC).timestamp()) // 3600 * 3600
    return coordinator.data.hours.get(timestamp, {}) if coordinator.data else {}
