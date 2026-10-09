# Copilot Instructions for trends.earth

## GitHub Actions

Use the authenticated `gh` CLI for GitHub operations, including workflow investigations. Do not read a `GITHUB_TOKEN` environment variable, construct REST requests, or use PowerShell API calls. Check authentication with `gh auth status`; if it is not configured, ask the user to authenticate with `gh auth login`.

```bash
# List recent workflow runs
gh run list --repo ConservationInternational/trends.earth --limit 10

# Inspect a run and list its jobs
gh run view RUN_ID --repo ConservationInternational/trends.earth

# Show logs for a job, or only failed-step logs for a run
gh run view --job JOB_ID --log --repo ConservationInternational/trends.earth
gh run view RUN_ID --log-failed --repo ConservationInternational/trends.earth

# Download the per-QGIS Docker log artifact
gh run download RUN_ID --repo ConservationInternational/trends.earth \
  --name docker-compose-logs-4.2-trixie --dir ./workflow-logs
```

The test workflow uploads Compose logs as artifacts even when a job fails. Use `gh run download` when the job log does not contain enough container detail.

## Repository Structure

This is the main Trends.Earth QGIS plugin repository. Key directories:

- `.github/workflows/` - CI/CD pipeline definitions
- `docker/` - Docker configuration for testing
- `LDMP/` - Main plugin code
- `test/` - Unit and integration tests

## Testing

### Local Testing

Run the full Docker-based suite from the repository root. The Linux runner defaults to the QGIS tag in `.env` or `release-3_34`; pass a tag to select a matrix image:

```bash
./run_tests.sh 3.44
./run_tests.sh 4.2-trixie
```

Optional arguments are `[qgis-version-tag] [test-target]`; the default target is `test_suite.test_package`. Use `SHOW_DOCKER_LOGS=true ./run_tests.sh 4.2-trixie` to print container logs after the run. `run_docker_test_environment.sh [qgis-version-tag]` only starts the Compose service for manual inspection.

On Windows, use the equivalent PowerShell runner:

```powershell
.\run_tests.ps1 -QgisVersion 3.44
.\run_tests.ps1 -QgisVersion 4.2-trixie
```

The Linux runner uses the isolated `trends-earth-tests` Compose project, reads only the needed image/tag settings from `.env`, builds the test image (`docker/test.Dockerfile`, which pulls the QGIS base image and preinstalls test dependencies), prints QGIS/GDAL/Python versions, runs the suite, and tears the project down. It does not source or print `.env`. Set `KEEP_TEST_CONTAINERS=true` to leave its service running. The PowerShell runner writes `.env` to select the image and uses the default Compose project for the repository; its default cleanup tears that project down, so avoid running it while another Compose stack from this checkout needs to remain up.

### End-to-end Tests (live API)

`test/e2e/` contains opt-in tests that drive the real plugin dialogs against the live Trends.Earth API. Per country, they run SDG 15.3.1 and drought (remote job → summary → summary JSON sanity checks in `test/e2e/summary_checks.py` → UNCCD/PRAIS package) and then build a combined package. They authenticate only with an OAuth2 client-credentials service credential (`TE_E2E_CLIENT_ID`/`TE_E2E_CLIENT_SECRET`, scopes `execution:read execution:write script:read user:read boundary:read`). They skip under `test_suite.test_package`. Run them with:

```bash
TE_E2E_CLIENT_ID=... TE_E2E_CLIENT_SECRET=... TE_E2E_COUNTRIES=STP ./run_tests.sh 3.44 test_suite.test_e2e
```

`.github/workflows/e2e.yaml` runs them on demand and every three days at 22:00 America/New_York, with one matrix job per ISO3 code from the `TE_E2E_COUNTRIES` repository variable (or the `countries` dispatch input). A `plan` job handles the DST and 3-day gating. Each job uploads `e2e-<ISO>-qgis-<tag>` with `summary.md`, the job JSON, summaries, packages and the Compose logs. Never print or log the client secret or access tokens.

### CI Testing

The workflow at `.github/workflows/test.yaml` tests `3.44`, and `4.2-trixie` in Docker. The informational Marshmallow 4 job uses the same matrix.

Compose builds `docker/test.Dockerfile` on top of `${IMAGE}:${QGIS_VERSION_TAG}`. The image build installs `requirements-testing.txt` plus `pytest`, `python-dotenv` and `coverage`, so containers do not install packages at startup. The Dockerfile handles differences in the newer Debian-based images: PEP 668 pip installs and the `git`, `unbuffer` and `pip` utilities. The entrypoint falls back to Xvfb for images without `supervisord`. Compose configures Qt for offscreen operation and disables the WebEngine sandbox for root-run containers. Add new test dependencies to `requirements-testing.txt` or the Dockerfile, not to workflow steps.

Common failure points:
- Startup or dependency-installation failures should be diagnosed from the uploaded `docker-compose-logs-{qgis-version-tag}` artifact or by rerunning locally with `SHOW_DOCKER_LOGS=true`.
