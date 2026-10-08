# Validation — 2026-10-08

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
brand assets ship with the integration. Remote results are recorded after the push.

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
