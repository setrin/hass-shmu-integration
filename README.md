# SHMÚ Weather for Home Assistant

A custom Home Assistant integration for Slovak weather forecasts from **SHMÚ**.
Select a city in the UI for measured current weather, hourly/daily forecasts,
and district weather warnings. No API key is needed.

## Features

- Searchable city dropdown populated from SHMÚ's location catalogue; Veľký Šariš
  (`32397`) is the initial selection. Add separate entries for other cities.
- **Combined** (default): ALADIN where available, then ECMWF for the longer range.
- **ALADIN only** or **ECMWF only**, selectable during setup or in integration options.
- Temperature, pressure, wind speed, gusts, direction, cloud cover and precipitation.
- Current measurements from a nearby station, including humidity and visibility when available.
- Active and upcoming district warnings, with severity, validity periods and descriptions.
- Downloadable diagnostics that omit the selected location.
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

Change the model strategy and observation station using the integration's **Configure** option. To change
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
manifest, translations and local brand icons. The repository is public.

1. In HACS, add `https://github.com/setrin/hass-shmu-integration` under
   **Custom repositories**, category **Integration**.
2. Download SHMÚ Weather and restart Home Assistant.
3. Follow the city-selection setup steps above.

A custom repository does not need inclusion in HACS's default catalogue.
See [HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/).

## What the values mean

Current temperature, humidity, wind, visibility and pressure use the newest usable
reading from the selected observation station. By default, this is the geographically
nearest station in our 27-station synoptic catalogue. A nearby station is **not a
measurement in your selected city**. Its name, distance and measurement time are
shown in weather attributes. For Veľký Šariš, automatic selection is **Kojšovská
hoľa**, a mountain station; use Configure to choose a station more representative
of your location (for example Košice), or select **Forecast model only**.

Missing measured fields remain unknown. Station pressure is approximately reduced
to sea level using station elevation and measured temperature. The condition icon
and cloud cover still come from the forecast, explicitly labeled by
`condition_source`; the observation feed has no documented cloud-cover field.
Icons use cloud cover, modeled rain and snow, with solar elevation for day/night.
They do not claim to detect observed fog or lightning.

Measurements are checked every **5 minutes**. If retrieval fails or the newest
usable reading is more than **30 minutes** old, current values fall back to the
forecast, with `current_weather_source` reflecting the change.

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
includes already elapsed modeled hours when available and retains them in memory
when a newer model run is fetched. After a restart, missing elapsed hours are recovered
from up to four earlier cycles per selected model, newest first. Earlier files fill
only missing past hours; current and future values keep the latest selected run.
If older files are unavailable, today can still be partial;
inspect `forecast_day_coverage` before treating today's totals as full-day values.
Incomplete future days are omitted from daily cards, while their hours remain in
the hourly forecast. A wet hour remains visible in the day's condition icon. The UI's daily high/low can understate true daily
extremes because it uses sampled temperatures. No extrapolation is performed
beyond each model's temperature horizon. Missing values stay unknown.

## Refresh and diagnostics

The integration checks SHMÚ's published-run index every **30 minutes**. It downloads
new run files only when their path changes. It does not assume files are available
at their initialization time. ALADIN's index currently lists 00/06/12/18 UTC;
ECMWF lists 00/12 UTC. If the index fails, it tries the four latest candidate cycles.
A missing/invalid new file falls back to an earlier run, then an in-memory cached run.
Runs older than **48 hours**, future runs, and runs without current-hour coverage
are rejected. Without any usable forecast or fresh observation, the entity becomes unavailable.
The cache is in memory and does not survive restart.

The weather entity exposes these useful state attributes:

- `current_weather_source`, `condition_source`, `current_model`, `current_forecast_time`
- `observation_station`, `observation_distance_km`, `observation_time`
- `forecast_mode`, `model_runs` (initialization times in UTC)
- `degraded_models` (models falling back, unavailable, or using a failed index)
- `aladin_forecast_end`, `hourly_values_interpolated`
- `forecast_day_coverage`

Download diagnostics from the integration's menu under Devices & services. The
report contains source availability, model timestamps and counts, but excludes
city/station identifiers, coordinates and warning descriptions.

There are no credentials. Requests go to `www.shmu.sk` and `opendata.shmu.sk`;
forecast and warning requests identify the selected public city/district. The integration is unofficial and not endorsed by SHMÚ.

## Additional weather sensors

Each city also exposes nine sensors:

| Sensor | Values |
| --- | --- |
| Next 24h temperature low / high | Minimum and maximum temperature, °C |
| Current temperature | Current temperature, °C |
| Current wind speed / gust | Current wind and gust, m/s |
| Next 24h wind minimum / maximum | Minimum and maximum forecast wind speed, m/s |
| Next 24h gust minimum / maximum | Minimum and maximum forecast hourly gust values, m/s |

The table lists native units; Home Assistant applies your unit preferences (for example,
km/h for wind) and allows per-entity unit changes.

Forecast extrema use the **next 24 hourly forecast buckets**, beginning with the
current hour. At 07:00, the window is 07:00 today through 07:00 tomorrow (end
exclusive): today's daytime high and the upcoming overnight low. At 07:35 it still
starts at 07:00; at 08:00 it advances to 08:00–08:00. Past-night values drop out as
the window advances. These are forecasts, not observed extrema. The gust minimum
is the smallest hourly gust forecast, not a lull measurement. Values follow your
selected ALADIN/ECMWF strategy.

These sensors expose `window_start` and `window_end` in UTC, plus `forecast_hours`,
`value_hours`, `expected_hours` (always 24) and `coverage_complete`. Missing fields or
short forecast coverage can affect extrema; missing values are never treated as
zero. The duration stays 24 real hours across daylight-saving changes, even when
local start/end clocks differ by an hour. The weather card's **daily** forecasts
continue to use Slovak calendar days; they are separate from these rolling sensors.

Existing sensor entity IDs are retained on upgrade, even if they contain `today`,
so dashboards, watch complications and automations continue referencing the same
entities. Their default display names change to “Next 24h…”. Any names you customized
remain yours to edit. The old `forecast_date` attribute is replaced by the window
start/end attributes.

Current temperature, wind and gust follow the weather entity's observation/model
fallback. A missing field in a fresh observation remains unknown; the `source`
attribute identifies the source used. Forecast sensors become unavailable if
forecast retrieval fails; fresh observations can still supply current values.
Update and restart Home Assistant, then choose the sensors on your SHMÚ device.

## Weather warnings

Each city adds two entities on the same device:

- **Weather warning**: on when an active **or upcoming** meteorological warning is
  published for the city's district. It can therefore alert you before an event starts.
- **Active warning level**: highest currently active level, **0–3**. Zero means
  no active warning; check upcoming warnings before treating that as an all-clear.

Both expose `active_warnings`, `upcoming_warnings`, `highest_upcoming_level`,
`district`, `last_checked` and `source_url`. Each warning includes event, severity,
start/end timestamps and SHMÚ's Slovak description. Add these entities to a dashboard
or use the binary sensor as an automation trigger. No notification is sent automatically.

Warnings refresh every **5 minutes**, so start/end transitions can lag by that amount.
Network, district-resolution or parsing failures make both entities **unavailable**,
not clear. A snapshot older than 15 minutes is also unavailable. Warnings are selected
using SHMÚ's own district boundaries and your forecast city's coordinates, independently
of the observation station. There is no radar, hydrological or smog-warning support.

The current website district page is used because the open-data CAP directory was
stale when checked on 2026-10-08. This is an unversioned HTML source; incompatible
layout changes are rejected. Use `source_url` to read the official warning page.

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
CI also runs Home Assistant hassfest and HACS validation. The HACS brands check
is excluded because the integration ships local brand assets; other checks run. Captured JSON files remain SHMÚ source data;
they are included as development fixtures and are not bundled into the installed
integration folder.

See [endpoint analysis](docs/shmu-api.md) for the verified wire format and samples.

See [validation results](docs/validation.md) for test versions, the current-version
local shutdown caveat, and checks still pending publication.

## Publishing updates

Use **Actions → Release → Run workflow** on the `main` branch:

1. Update `version` in `custom_components/shmu/manifest.json`, commit and push to
   `main`. Use `0.1.1` for a fix, `0.2.0` for a feature, etc. The initial release
   can use the current manifest version (`0.4.0`).
2. Enter that version **without** `v` in the workflow's **Version** field.
3. Leave **Publish release** unchecked to test the entire workflow without creating
   a tag or release. Check it when you intend to publish.
4. The workflow checks the branch and manifest version, rejects existing or older
   versions, and runs lint, formatting, both Home Assistant test versions, hassfest
   and HACS validation.
5. If publishing is selected and every check passes, it creates `vX.Y.Z` and a
   published GitHub Release with generated notes, pointing to the exact tested
   commit. HACS can then detect the release on its next update check.

No additional secret or personal access token is needed; publication uses GitHub's
built-in token. Normal pushes run tests but do not publish. Release jobs are
serialized, and only the publishing job has repository write permission. After
installing an integration update through HACS, restart Home Assistant.

## Attribution

Weather data and warning text are provided by SHMÚ. The small observation-station
catalogue and distance helper are adapted from [vaind/ha-shmu](https://github.com/vaind/ha-shmu)
under the MIT license; its copyright and license are included in the installed
integration's `NOTICE`. The integration supplies the missing public Sectigo TLS
intermediate for the observation server, retaining certificate and hostname verification.

This license covers the integration code, documentation and original generic
weather icon. It does not grant rights to SHMÚ's source data, name or trademarks.
