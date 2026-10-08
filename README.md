# SHMÚ Weather for Home Assistant

A custom Home Assistant integration for Slovak weather forecasts from **SHMÚ**.
Select a city in the UI and get a weather entity with current **modeled** conditions,
hourly forecasts and daily forecasts. No API key is needed.

## Features

- Searchable city dropdown populated from SHMÚ's location catalogue; Veľký Šariš
  (`32397`) is the initial selection. Add separate entries for other cities.
- **Combined** (default): ALADIN where available, then ECMWF for the longer range.
- **ALADIN only** or **ECMWF only**, selectable during setup or in integration options.
- Temperature, pressure, wind speed, gusts, direction, cloud cover and precipitation.
- English and Slovak setup text.
- Published-run discovery, cached forecast files, fallback to earlier usable runs,
  and continued operation when only one model is available in combined mode.

## Install locally

Requires Home Assistant **2025.12 or newer**.

1. Copy `custom_components/shmu` into your Home Assistant configuration directory
   under `custom_components/shmu`.
2. Restart Home Assistant.
3. Open **Settings → Devices & services → Add integration → SHMÚ Weather**.
4. Select your city and forecast source.
5. Add the resulting weather entity to a weather forecast card.

Change the model strategy using the integration's **Configure** option. To change
cities, add the new city and remove the old entry if no longer needed.

For a dashboard card, use the actual entity ID shown by Home Assistant:

```yaml
type: weather-forecast
entity: weather.shmu_velky_saris
forecast_type: daily
```

Forecasts are exposed through Home Assistant's `weather.get_forecasts` action;
they are not stored in a `forecast` state attribute. Both `daily` and `hourly`
forecast types are supported.

## HACS

Repository: [setrin/hass-shmu-integration](https://github.com/setrin/hass-shmu-integration).

The repository includes HACS's integration layout, `hacs.json`, the integration
manifest, translations and local brand icons. It is initially **private**; use
manual installation from an authenticated clone. Standard HACS installation
requires a public repository.

If the repository is made public:

1. In HACS, add `https://github.com/setrin/hass-shmu-integration` under
   **Custom repositories**, category **Integration**.
2. Download SHMÚ Weather and restart Home Assistant.
3. Follow the city-selection setup steps above.

A custom repository does not need inclusion in HACS's default catalogue.
See [HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/).

## What the values mean

**Current weather is an estimate from the forecast for the current hour, not a live
station reading.** The supplied endpoints do not provide live observations or
humidity. Conditions/icons are a conservative heuristic based on cloud cover,
rain and snow; clear sky uses the selected city's solar elevation for day/night.
They do not claim to detect fog, lightning or other unprovided phenomena.

ALADIN has hourly data, about 102 hours in the inspected run. ECMWF has ensemble
statistics out to 240 hours. We use the **median** for scalar ECMWF fields and the
most frequent ensemble wind sector. ECMWF temperatures and other instantaneous
fields are linearly interpolated from 3-/6-hour samples to hourly display values;
wind directions interpolate across the shortest arc. Gusts are also interpolated
between the supplied interval-maximum samples. These are display estimates, not
new hourly model output.

Precipitation is already an **interval amount**, not a running accumulation.
ALADIN totals cover the preceding hour; ECMWF totals cover the preceding six hours.
Each is allocated to the hours it covers, with ECMWF spread uniformly over six
hours. An hourly forecast timestamp marks the **start** of its hour. This makes
hourly/daily totals consistent through a model transition and across midnight.
Snowfall is water equivalent and is used only for condition classification.

Daily forecasts use `Europe/Bratislava` calendar days, including 23-/25-hour DST
days. High/low are extrema of the hourly temperature series, not extrema across
ensemble members. Daily wind/gust values are the maxima of that day's normalized
series. Daily rainfall is the sum of available hourly estimates. Today's forecast
includes already elapsed modeled hours when available. First/last days can be
partial; inspect `forecast_day_coverage` (actual versus expected hours) before
using totals as full-day values. The UI's daily high/low can understate true daily
extremes because it uses sampled temperatures. No extrapolation is performed
beyond each model's temperature horizon. Missing values stay unknown.

## Refresh and diagnostics

The integration checks SHMÚ's published-run index every **30 minutes**. It downloads
new run files only when their path changes. It does not assume files are available
at their initialization time. ALADIN's index currently lists 00/06/12/18 UTC;
ECMWF lists 00/12 UTC. If the index fails, it tries the four latest candidate cycles.
A missing/invalid new file falls back to an earlier run, then an in-memory cached run.
Runs older than **48 hours**, future runs, and runs without current-hour coverage
are rejected. Without any usable selected model, the entity becomes unavailable.
The cache is in memory and does not survive restart.

The weather entity exposes these useful state attributes:

- `current_weather_source`, `current_model`, `current_forecast_time`
- `forecast_mode`, `model_runs` (initialization times in UTC)
- `degraded_models` (models falling back, unavailable, or using a failed index)
- `aladin_forecast_end`, `hourly_values_interpolated`
- `forecast_day_coverage`

There are no credentials. Requests go to `www.shmu.sk` and identify the selected
public city ID. The integration is unofficial and not endorsed by SHMÚ.

## Development

```sh
python3.13 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q
```

Tests use captured source fixtures and mocked HTTP. Home Assistant lifecycle tests
use real configuration flows, platform setup and weather forecast services in an
isolated instance; they do not require your running Home Assistant installation.
The CI workflow runs the same checks. Captured JSON files remain SHMÚ source data;
they are included as development fixtures and are not bundled into the installed
integration folder.

See [endpoint analysis](docs/shmu-api.md) for the verified wire format and samples.

See [validation results](docs/validation.md) for test versions, the current-version
local shutdown caveat, and checks still pending publication.
