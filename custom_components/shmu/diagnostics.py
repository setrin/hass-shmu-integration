"""A whitelist of health data; no selected location or raw source payloads."""

from datetime import UTC, datetime


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    data = coordinator.data
    live = coordinator.live.data or {}
    observation = live.get("observation")
    warnings = live.get("warnings")
    return {
        "forecast_mode": coordinator.mode,
        "forecast_update_success": coordinator.last_update_success,
        "model_runs": {key: run.initialized.isoformat() for key, run in data.runs.items()}
        if data
        else {},
        "forecast_hour_count": len(data.hours) if data else 0,
        "degraded_models": data.degraded_models if data else [],
        "observation_available": observation is not None,
        "observation_age_seconds": (
            datetime.now(UTC) - datetime.fromisoformat(observation["measured_at"])
        ).total_seconds()
        if observation
        else None,
        "warnings_available": warnings is not None,
        "warnings_checked_at": warnings.get("checked_at") if warnings else None,
        "warning_count": len(warnings["alerts"]) if warnings else None,
    }
