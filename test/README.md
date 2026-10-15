# Trends.Earth plugin tests

## Generated custom-data end-to-end tests (offline)

[`e2e/test_custom_population.py`](e2e/test_custom_population.py) runs without
API credentials or network access. It imports generated land-cover and
population rasters through the real import dialogs and threaded workers, then
runs the production land degradation and drought summary engines, including
JSON and Excel reporting and persisted raster outputs. Drought uses a water
mask derived from the imported land cover; productivity, SOC, SPI and JRC
vulnerability inputs are generated as well.

Eight scenarios cover all three population input units, total and
sex-disaggregated population, and legacy count rasters without units metadata.
An additional 12 scenarios vary imported land-cover resolution between
0.0005, 0.001 and 0.002 degrees (finer than, equal to, and coarser than the
productivity/SPI grid), with total and sex-disaggregated population. Each
resolution is tested both with custom population imports and without them,
using generated WorldPop-style people-per-hectare inputs. These fixtures
exercise the downloaded-population metadata path but do not download live
WorldPop data. The live API suite continues to cover actual remote datasets.
Both summaries check population totals and affected classes after regridding;
SDG uses its productivity reference resolution, while drought uses the finest
input resolution, including the native land-cover-derived water mask.
The population grid is ten times coarser in each dimension than the land-cover
and SPI grids in the original eight scenarios. Tests verify conservation of
**1,750.875 people**, affected
population by class, fractional Float32 values, signed exposure outputs,
nodata, units metadata saved to disk, and output readability after temporary
normalization inputs have been cleaned up.

These tests run in the normal suite and alongside the live E2E suite, or alone:

```bash
./run_tests.sh 3.44 test_suite.test_e2e_custom
```

When testing unreleased coordinated plugin/algorithms changes, the container
must use the matching algorithms source or package, not an older pinned release.

## End-to-end tests against the live API (optional)

[`e2e/test_remote_pipelines.py`](e2e/test_remote_pipelines.py) drives the plugin dialogs in the QGIS
Docker test environment against the real Trends.Earth API. For each country it:

- submits the SDG 15.3.1 and drought vulnerability jobs, waits for them and
  downloads the results;
- runs the SDG 15.3.1 and drought summaries;
- sanity checks each summary JSON (see below);
- builds SDG-only, drought-only and combined UNCCD/PRAIS packages.
- submits productivity (trajectory, performance and state), land cover and
  soil organic carbon through their separate remote dialogs, waits for GEE
  execution and downloads the results;
- selects those three separate outputs in the SDG 15.3.1 calculation dialog
  and runs the same summary JSON sanity checks on the resulting indicator.

The separate-input calculation covers the baseline: productivity 2001–2015
(state baseline 2001–2012, comparison 2013–2015), land cover and SOC 2000–2015.
Population comes from the existing all-in-one baseline job; the productivity,
land cover and SOC layers must come from their own submissions, not that job.
Both the selected job IDs and the local calculation's input file paths are
verified. This additional baseline summary is checked independently and does
not replace the existing baseline/reporting-period summaries or packages.

The test authenticates as a dedicated test user with an OAuth2 **service
credential** (client-credentials grant), never with an email and password. The
credential needs the scopes `execution:read execution:write script:read
user:read boundary:read`, and the test user must be allowed to run Google Earth
Engine jobs. The tests are skipped unless they are run through
`test_suite.test_e2e` with the credential set:

```bash
TE_E2E_CLIENT_ID=... TE_E2E_CLIENT_SECRET=... TE_E2E_COUNTRIES=STP \
  ./run_tests.sh 3.44 test_suite.test_e2e
```

Script IDs, versions and configuration come from the plugin's
[`LDMP/data/scripts.json`](../LDMP/data/scripts.json) via `conf.KNOWN_SCRIPTS`,
just as they do in the plugin UI. The e2e harness selects scripts by name,
without pinning UUIDs, versions or copying script definitions. Updating that
file updates the scripts exercised by the next test run.

| Variable | Purpose | Default |
| --- | --- | --- |
| `TE_E2E_CLIENT_ID`, `TE_E2E_CLIENT_SECRET` | Service credential (required) | none |
| `TE_E2E_API_URL` | API base URL | plugin default |
| `TE_E2E_COUNTRIES` | Comma-delimited ISO3 codes | `FJI,STP,GUY` |
| `TE_E2E_TIMEOUT_MIN` | Remote job and download timeout (minutes) | `240` |
| `TE_E2E_POLL_SEC` | Remote polling interval (seconds) | `60` |
| `TE_E2E_SUBMIT_ATTEMPTS` | Attempts per remote submission on rate limits, 5xx or no response | `4` |
| `TE_E2E_LOCAL_TIMEOUT_MIN` | Timeout per local summary/package job (minutes) | `60` |
| `TE_E2E_OUTPUT_DIR` | Where job JSON, summaries and packages are copied | temporary dir |
| `TE_E2E_CHECK_AREA_TOL` | Allowed difference between summary area and AOI area | `0.10` |
| `TE_E2E_CHECK_MAX_NODATA_FRAC` | No data fraction that fails a summary check | `0.30` |
| `TE_E2E_CHECK_WARN_NODATA_FRAC` | No data fraction that triggers a warning | `0.10` |

### Remote submissions

Jobs are submitted through the plugin dialogs. Jobs that the API queues (status
`PENDING`, because the user already has the maximum number of running jobs) count
as submitted. If the plugin gets no job back, the test checks whether the server
created the execution anyway (matching on task name). If it didn't, the test
retries after HTTP 429, 5xx or no response, honouring `Retry-After`. A failure
reports the HTTP status and response body. Each country submits seven remote jobs
(baseline, two reporting periods, drought, productivity, land cover and SOC).
The API rate-limits the run endpoint (by default 10 per minute and 40 per hour
per user). Repeated runs in
one hour can therefore hit the limit.

While polling, `PENDING`, `READY`, `RUNNING` and `CANCELLING` are in progress.
Only `FAILED`, `CANCELLED` or a timeout stop the chain. A job still queued or
running at `TE_E2E_TIMEOUT_MIN` is reported with its last status rather than as
failed. Only three jobs per user run at once by default, and the rest wait in
the queue, so allow for queue time when choosing the timeout.

### Summary checks

Before packaging, [`e2e/summary_checks.py`](e2e/summary_checks.py) checks each
summary JSON. A failed check stops that indicator's package and the combined
package. The combined-package test is skipped when a prerequisite summary check
fails; the originating pipeline test reports the failure. Errors are:

- missing, negative or non-numeric values, or missing classes;
- a total area that differs from the area of the country's boundary polygon
  (`TE_E2E_CHECK_AREA_TOL`), computed from the plugin's boundaries dataset with
  an equal-area projection, so any ISO3 code can be checked;
- tabulations of the same pixels that do not add up to the same total (1%
  tolerance). For SDG 15.3.1 these are the SDG, land cover, productivity and SOC
  summaries, the land cover area for each year, the status summaries and the
  baseline vs reporting crosstabs, in every period. For drought they are the
  area by drought class in every year;
- non-water area larger than the total area, or land cover / productivity
  transition crosstabs larger than the total area;
- too much No data area or population (`TE_E2E_CHECK_MAX_NODATA_FRAC`);
- no Stable area, no valid (Improved/Stable/Degraded) area, or fewer than two
  land cover classes;
- for drought: non-contiguous years, no drought area in any year, no Non-drought
  area in any year, or a drought vulnerability index that is missing or outside
  0–100 (inclusive);
- missing or zero population, male + female not matching the total, or an
  implausible population density (outside 0.01–50,000 people per sq km);
- missing population classes in any SDG period or drought year. Downloaded
  population bands must also have supported units (untagged legacy counts are
  allowed), a year, and either total population or a complete male/female pair.

Unusual but possible results are warnings: zero Improved or Degraded area, 95%
or more of the valid area in a single class (all Stable or all Degraded),
moderate No data, no reporting periods,
large year-to-year changes in SOC stock or population, and empty crosstabs.
Warnings are logged and listed in `summary.md`. The full results are saved to
`<ISO>/<sdg|drought|sdg_separate>/checks/checks.json` and in `summary.json`.

The checks have offline unit tests in
[`e2e/test_summary_checks.py`](e2e/test_summary_checks.py), which run with the
normal test suite.
[`e2e/test_subindicators.py`](e2e/test_subindicators.py) also tests the real dialog
submission payloads offline and verifies separate-input selection and provenance.

A run takes one to several hours. The [`e2e.yaml`](../.github/workflows/e2e.yaml) workflow
runs it on demand, and every three days at 22:00 US Eastern, with one job per
country. It needs:

- repository secrets `TE_E2E_CLIENT_ID` and `TE_E2E_CLIENT_SECRET`;
- the repository variable `TE_E2E_COUNTRIES` (for example `FJI,STP,GUY`);
- optionally, the variables `TE_E2E_API_URL` and `TE_E2E_CHECK_*` (summary check thresholds).

Results are uploaded as `e2e-<ISO>-qgis-<tag>` artifacts.
