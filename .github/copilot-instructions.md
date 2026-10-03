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

The Linux runner uses the isolated `trends-earth-tests` Compose project, reads only the needed image/tag settings from `.env`, pulls the image, installs test dependencies, prints QGIS/GDAL/Python versions, runs the suite, and tears the project down. It does not source or print `.env`. Set `KEEP_TEST_CONTAINERS=true` to leave its service running. The PowerShell runner writes `.env` to select the image and uses the default Compose project for the repository; its default cleanup tears that project down, so avoid running it while another Compose stack from this checkout needs to remain up.

### CI Testing

The workflow at `.github/workflows/test.yaml` tests `release-3_34`, `release-3_36`, `3.44`, and `4.2-trixie` in Docker. The informational Marshmallow 4 job uses the same matrix.

The shared Docker setup handles differences in the newer Debian-based images: PEP 668 pip installs, the `git` and `unbuffer` utilities, and images without `supervisord` (the entrypoint falls back to Xvfb). Compose configures Qt for offscreen operation and disables the WebEngine sandbox for root-run containers. `coverage` is installed with the test dependencies; do not rely on the test harness to install it dynamically.

Common failure points:
- QGIS 4 currently runs the suite but has five job-filter test errors because `setFilterRegExp` is unavailable, plus the NumPy single-element-array error.
- QGIS 3.44 currently has the NumPy single-element-array error.
- Startup or dependency-installation failures should be diagnosed from the uploaded `docker-compose-logs-{qgis-version-tag}` artifact or by rerunning locally with `SHOW_DOCKER_LOGS=true`.
