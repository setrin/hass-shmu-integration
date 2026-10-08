# SHMÚ endpoint analysis

Inspected on 2026-10-08 using all four supplied JSON files, the city catalogue,
the meteogram page's JavaScript and the published-product index.

## Location and model selection

[City catalogue](https://www.shmu.sk/api/v1/nwp/getjsonaladinstations) returns a flat
array of 1,068 objects in this snapshot. An example:

```json
{
  "station_id": 32397,
  "station_name": "Veľký Šariš",
  "lat": "49.040000",
  "lon": "21.200000",
  "district_code": 707
}
```

`station_id` is a forecast-location identifier, not proof of a live measurement
station at that point. The forecast identifies the location as `si_id` (a string),
with `location_name`, string coordinates and `elevation: "263"` metres.
ALADIN's model orography is approximately 327.558 m and ECMWF's 425.802 m;
these differ from actual location elevation. Temperature comments say the values
are adjusted to the real location altitude.

The [page](https://www.shmu.sk/sk/?page=2673&nwp_mesto=32397#alaef) selects the city
through `nwp_mesto`. Its `#alaef` fragment selects **A-LAEF**, a separate ensemble
product displayed with optional ALADIN overlay. It does not mean the ALADIN JSON
is an ensemble. This integration implements the requested `aladin` and `ecmwf`
products, not `a-laef`.

## Published-run discovery

The page's JavaScript calls
[`/api/v1/nwp/getstationproducts?station=32397`](https://www.shmu.sk/api/v1/nwp/getstationproducts?station=32397).
It returns a `station` object and a `data` array:

```json
{
  "type": "aladin",
  "dt_runtime": "2026-10-08 12:00:00",
  "runtime": 1791460800,
  "file_link": "aladin/2026-10-08/32397_2026-10-08_12.json"
}
```

`runtime` is the model initialization time as Unix seconds. The relative `file_link`
is appended to `https://www.shmu.sk/data/datanwp/json/`. Sorting by numeric runtime
per model avoids relying on array order or guessed publication delays. In the
snapshot ALADIN has 00, 06, 12 and 18 UTC runs; ECMWF has 00 and 12 UTC runs. The
latest ALADIN and ECMWF runs can differ, so they are selected independently.

## Filename semantics

```text
/data/datanwp/json/{model}/{YYYY-MM-DD}/{city_id}_{YYYY-MM-DD}_{HH}.json
```

Both dates and `HH` refer to initialization in **UTC**, confirmed by the payload's
`data_date_time` and the first temperature-series timestamp. They are not the
forecast-valid date of every row and are not an upload timestamp.

00/12 UTC correspond to 02:00/14:00 under Slovak summer time and 01:00/13:00 under
winter time. Initialization time alone cannot establish actual availability.
The integration follows published products and polls for new availability.

## JSON format and units

Each parameter is an object with a Slovak `comment`, a `unit` and `data`. ALADIN
rows are `[unix_seconds, value]`; the initial value of interval fields is commonly
`null`. ECMWF scalar parameters have:

```json
"columns": ["Time", "Minimum", "Lower quartile", "Median", "Upper quartile", "Maximum"]
```

The corresponding row is `[time, min, q1, median, q3, max]`. Column names determine
the median's position. The minimum and maximum columns describe ensemble spread;
they must not be mistaken for the day's temperature low/high.

| Parameter | Unit | ALADIN | ECMWF |
| --- | --- | --- | --- |
| `Air_temperature_at_2m` | °C | Hourly instantaneous | Ensemble median, 3h then 6h |
| `Mean_sea_level_pressure` | hPa | Hourly | Ensemble median, 3h then 6h |
| `Wind_speed_at_10m` | m/s | Hourly | Ensemble median, 3h then 6h |
| `Wind_gust_at_10m` | m/s | Hourly interval field | Ensemble median, 6h |
| `Wind_direction_at_10m` | ° / direction | Degrees | Counts in eight direction sectors |
| `Total_cloud_cover` | % | Hourly | Ensemble median, 3h then 6h |
| `Total_precipitation` | mm | Preceding 1h amount | Preceding 6h amount |
| `Snowfall` | mm | Preceding 1h water equivalent | Preceding 6h water equivalent |
| `Minimum_temperature_in_the_last_hour` | °C | Preceding 1h minimum | Not present |
| `Maximum_temperature_in_the_last_hour` | °C | Preceding 1h maximum | Not present |
| `Minimum_temperature_in_the_last_6_hours` | °C | Not present | Ensemble of preceding 6h minima |
| `Maximum_temperature_in_the_last_6_hours` | °C | Not present | Ensemble of preceding 6h maxima |
| `Orography` | m | Single model-altitude value | Single model-altitude value |

Low/medium/high cloud layers are also present but the integration uses total cloud
cover. Humidity, explicit weather-condition codes and live observation timestamps
are absent from these samples.

ECMWF wind direction has `columns: ["Time","N","NE","E","SE","S","SW","W","NW"]`.
Values are member counts (51 members in sampled rows), not quantiles or degrees.
The implementation takes the most frequent sector; ties use the first sector in
that order. This is a representative direction, not a circular ensemble mean.

Parameter arrays have different lengths and timestamps. They must be joined by
timestamp, not row index. Precipitation's first ECMWF row is at +6h; it does not
have the temperature array's initial +0h row or the +3h row.

## Verified supplied runs

| Model | Initialization UTC | Temperature rows | Last valid timestamp UTC |
| --- | --- | --- | --- |
| ALADIN | 2026-10-08 00:00 | 103, hourly | 2026-10-12 06:00 |
| ECMWF | 2026-10-07 12:00 | 65, 3h to +144h then 6h | 2026-10-17 12:00 |
| ECMWF | 2026-10-06 12:00 | 65, same schema | 2026-10-16 12:00 |
| ECMWF | 2026-10-06 00:00 | 65, same schema | 2026-10-16 00:00 |

The integration excludes the final instantaneous endpoint from hourly buckets,
because there is no following hour of coverage: 102 ALADIN buckets and 240 ECMWF
buckets in the first two samples. Missing temperature hours can reduce coverage.

Sources: [ALADIN sample](https://www.shmu.sk/data/datanwp/json/aladin/2026-10-08/32397_2026-10-08_00.json),
[ECMWF Oct 7 12Z](https://www.shmu.sk/data/datanwp/json/ecmwf/2026-10-07/32397_2026-10-07_12.json),
[ECMWF Oct 6 12Z](https://www.shmu.sk/data/datanwp/json/ecmwf/2026-10-06/32397_2026-10-06_12.json),
[ECMWF Oct 6 00Z](https://www.shmu.sk/data/datanwp/json/ecmwf/2026-10-06/32397_2026-10-06_00.json).

## Interpretation and limits

Combined mode chooses ALADIN independently for each valid hour and ECMWF for the
remaining hours. Six-hour ECMWF precipitation is apportioned before merging so a
partial interval at the handoff cannot be counted in full on top of ALADIN rain.
Interpolation does not increase the model's information content. Adding marginal
ensemble medians over time does not produce the exact ensemble median of the daily
rainfall total. Daily highs/lows use the normalized temperature series rather than
the provided interval-extreme fields; they are approximate. First/last days may be
partial and this is exposed in the entity attributes.

The public web endpoints have no versioned contract established by this research.
Schema/unit/identity validation rejects incompatible data, and the fixture tests
make the observed contract explicit.
