# Validation — 2026-10-08

## Clean local checks

- Python 3.13.14, Home Assistant 2025.12.5: **27 tests passed**, exit status 0.
- Ruff lint and formatting checks passed.
- Live SHMÚ client check succeeded for city `32397`: both ALADIN and ECMWF selected
  the published `2026-10-08T12:00:00Z` runs, with no degraded models.
- Live decoding produced modeled current weather and 11 local-date forecast entries
  spanning the 10-day horizon (edge dates can be partial).
- Repository destination: `https://github.com/setrin/hass-shmu-integration` (public).

The tests cover actual sample decoding, median and wind-sector selection,
precipitation conservation, ALADIN-to-ECMWF handoff, nulls, unit/identity validation,
DST and partial days, HTTP errors, run discovery, caching and expiry. Home Assistant
lifecycle tests cover config flow, duplicate prevention, retry, real weather services,
forecast subscriptions, unavailable/recovery state, options reload and unloading.
The latter use mocked SHMÚ network responses and a local Home Assistant instance,
not the user's running Home Assistant server.

## Current-version caveat

Python 3.14.6, Home Assistant 2026.10.0: all **27 assertions pass**, including
configuration and weather services, but the interpreter exits with a segmentation
fault (139) during final garbage collection. This reproduces with both Homebrew
and standalone Python 3.14.6 on this Mac. Pure forecast-only tests exit cleanly;
the lifecycle suite triggers the shutdown issue. Its root cause is not established.
Do not treat this as a clean end-to-end 2026.10 certification.

The test harness handles the newer device-registry initialization and supplies the
mock-only stream-writer argument missing from aioresponses 0.7.9 under aiohttp 3.14.
Neither compatibility adjustment changes the integration's production behavior.
The initial GitHub Actions Linux CI matrix passed for both Home Assistant releases:
[run 37836147255](https://github.com/setrin/hass-shmu-integration/actions/runs/37836147255).
This confirms the tests complete cleanly on Linux; the local macOS shutdown issue
above remains separately documented.

## Publication and remaining checks

The manifest links and maintainer are configured for `setrin/hass-shmu-integration`.
HACS metadata and local brand assets are present, and the repository is public.
HACS remote validation has not been run. The Release workflow supports a dry run
and explicit publication after the same test matrix succeeds.

- Review the GitHub Actions matrix and investigate any current-version failure.
- Install on the target Home Assistant instance and verify its UI/card.
