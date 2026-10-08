# Validation — 2026-10-08

## Version 0.3.0 — additional sensors

- Python 3.13 / Home Assistant 2025.12.5: **62 tests passed**, exit status 0.
- Ruff lint, formatting and whitespace checks passed.
- Adds nine sensors for today's forecast temperature/wind/gust extrema and
  current temperature/wind/gust, sharing current-weather selection with the weather entity.
- Tests verify local-date boundaries, 23/25-hour DST coverage, partial/missing
  values, zero wind, HA unit conversion, observations during forecast outages,
  unavailable daily sensors, fallback, hourly clock callback and listener cleanup.
- GitHub's test matrix, hassfest and HACS run on the pushed commit; consult the
  Actions tab for final results. No new external endpoints are introduced.
- Manifest prepared as 0.3.0; a GitHub release is a separate publication step.

## Version 0.2.0

- Python 3.13.14, Home Assistant 2025.12.5: **59 tests passed**, exit status 0.
- Ruff lint, formatting and whitespace checks passed.
- Live observation request succeeded with trusted-root and hostname verification:
  Kojšovská hoľa, measured 2026-10-08T20:24Z, 12.0°C. Automatic selection for
  Veľký Šariš is this mountain station, 32.6 km away; setup/options allow overriding it.
- Live district-map lookup resolves Veľký Šariš (49.04, 21.2) to Prešov (`PO`).
- Live Prešov warning page parsed successfully with no warnings at the check time.
  The Bratislava response contained a level-1 wind warning, 2026-10-08T21:00Z
  through 2026-10-09T02:00Z; parsing preserves its text and times.
- SHMÚ's CAP directory listed only September 7/9 snapshots during the October 8
  investigation, so it is not used for current warning state.

Tests cover source fixtures, units/nulls, fixed-CET observation timestamps,
freshness/future rejection, bounded discovery/fallback, source independence,
warning parsing/expiry/empty pages/malformed pages/multiple nested warning tables,
district matching, certificate-verification settings, partial future days,
23/25-hour DST days, retained earlier modeled hours and daily rain icons.

Real Home Assistant lifecycle tests exercise setup, forecast services/subscriptions,
observation attributes and model fallback, active/upcoming/unavailable warning states,
options reload, diagnostics privacy and listener cleanup on unload. Network responses
are mocked in these tests; they do not exercise the user's running HA installation.

The updated CI runs the Linux HA 2025.12.5/Python 3.13 and HA 2026.10.0/Python 3.14
matrix, plus hassfest and HACS checks. HACS's brands check is excluded because local
brand assets ship with the integration. In the first new CI run, HA 2026.10 and
hassfest passed. HACS detected an unrecognized license due to an explanatory footer;
the footer was moved to README, keeping the MIT text and scope unchanged.
Final CI results are available in the repository's Actions tab.

## Earlier baseline

The initial Linux matrix passed for both HA versions:
[run 37836147255](https://github.com/setrin/hass-shmu-integration/actions/runs/37836147255).
Live JSON forecasting selected both published 2026-10-08T12:00Z model runs.

On this Mac, the earlier HA 2026.10/Python 3.14 lifecycle suite passed its assertions
but crashed during interpreter shutdown. Both Homebrew and standalone Python showed
that behavior; Linux CI completed cleanly. The integration has not been installed
on the user's actual Home Assistant server as part of these checks.

## Publication

The public repository is `setrin/hass-shmu-integration`; the manifest is prepared
for version 0.2.0. The Release workflow requires all four validation jobs and supports
an explicit publication switch. Pushing these changes does not create a release.
