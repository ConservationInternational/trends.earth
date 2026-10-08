# Trends.Earth plugin tests

## End-to-end tests against the live API (optional)

[`e2e/test_remote_pipelines.py`](e2e/test_remote_pipelines.py) drives the plugin dialogs in the QGIS
Docker test environment against the real Trends.Earth API. For each country it:

- submits the SDG 15.3.1 and drought vulnerability jobs, waits for them and
  downloads the results;
- runs the SDG 15.3.1 and drought summaries;
- builds SDG-only, drought-only and combined UNCCD/PRAIS packages.

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

| Variable | Purpose | Default |
| --- | --- | --- |
| `TE_E2E_CLIENT_ID`, `TE_E2E_CLIENT_SECRET` | Service credential (required) | none |
| `TE_E2E_API_URL` | API base URL | plugin default |
| `TE_E2E_COUNTRIES` | Comma-delimited ISO3 codes | `FJI,STP,GUY` |
| `TE_E2E_TIMEOUT_MIN` | Remote job and download timeout (minutes) | `240` |
| `TE_E2E_POLL_SEC` | Remote polling interval (seconds) | `60` |
| `TE_E2E_LOCAL_TIMEOUT_MIN` | Timeout per local summary/package job (minutes) | `60` |
| `TE_E2E_OUTPUT_DIR` | Where job JSON, summaries and packages are copied | temporary dir |

A run takes one to several hours. The [`e2e.yaml`](../.github/workflows/e2e.yaml) workflow
runs it on demand, and every three days at 22:00 US Eastern, with one job per
country. It needs:

- repository secrets `TE_E2E_CLIENT_ID` and `TE_E2E_CLIENT_SECRET`;
- the repository variable `TE_E2E_COUNTRIES` (for example `FJI,STP,GUY`);
- optionally, the variable `TE_E2E_API_URL`.

Results are uploaded as `e2e-<ISO>-qgis-<tag>` artifacts.
