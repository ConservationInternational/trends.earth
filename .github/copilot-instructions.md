# Copilot Instructions for trends.earth

## Accessing GitHub Actions Workflow Logs

When investigating CI failures or checking workflow runs, use the GitHub MCP (Model Context Protocol) server that is configured in `.vscode/settings.json`.

### Setup

The MCP server for GitHub is already configured and uses the `GITHUB_TOKEN` environment variable for authentication:

```json
"mcp.servers": {
    "github": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {
            "GITHUB_PERSONAL_ACCESS_TOKEN": "${env:GITHUB_TOKEN}"
        }
    }
}
```

### How to Access Workflow Logs

Use PowerShell scripts to interact with the GitHub REST API, avoiding `gh` CLI commands or manual API calls:

| Step | Goal | API Endpoint |
|------|------|-------------|
| 1 | List recent workflow runs | `GET /repos/{owner}/{repo}/actions/runs` |
| 2 | Get jobs for a run | `GET /repos/{owner}/{repo}/actions/runs/{run_id}/jobs` |
| 3 | Get logs for a job | `GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs` |
| 4 | Download artifact logs | `GET /repos/{owner}/{repo}/actions/artifacts/{artifact_id}/zip` |

#### 1. Get Recent Workflow Runs

```powershell
$token = [System.Environment]::GetEnvironmentVariable('GITHUB_TOKEN', 'User')
$headers = @{ Authorization = "Bearer $token"; Accept = "application/vnd.github+json" }
$response = Invoke-RestMethod -Uri "https://api.github.com/repos/ConservationInternational/trends.earth/actions/runs?per_page=10" -Headers $headers
$response.workflow_runs | Select-Object -First 5 name, status, conclusion, created_at, id
```

#### 2. Get Jobs for a Specific Run

```powershell
$runId = <run_id_from_above>
$jobs = Invoke-RestMethod -Uri "https://api.github.com/repos/ConservationInternational/trends.earth/actions/runs/$runId/jobs" -Headers $headers
$jobs.jobs | Select-Object name, status, conclusion, started_at
```

#### 3. Get Logs for a Failed Job

```powershell
$jobId = <job_id_from_above>
$logs = Invoke-RestMethod -Uri "https://api.github.com/repos/ConservationInternational/trends.earth/actions/jobs/$jobId/logs" -Headers $headers
$logs | Select-String -Pattern "error|fail|Error|FAIL" -Context 3,3 | Select-Object -First 20
```

#### 4. Download Artifact Logs

```powershell
$artifactId = <artifact_id_from_workflow>
$artifactUrl = "https://api.github.com/repos/ConservationInternational/trends.earth/actions/artifacts/$artifactId/zip"
Invoke-RestMethod -Uri $artifactUrl -Headers $headers -OutFile "$env:TEMP\logs.zip"
Expand-Archive -Path "$env:TEMP\logs.zip" -DestinationPath "$env:TEMP\logs" -Force
Get-Content "$env:TEMP\logs\docker-compose-logs.txt"
```

### Common Workflow Investigation Pattern

1. **List recent runs** to find the failing workflow
2. **Get jobs for that run** to identify which specific job failed
3. **Retrieve job logs** to see the detailed error output
4. **Download artifacts** if docker-compose logs or other debug files are available

### Example: Full Investigation Flow

```powershell
# 1. Find recent CI failures
$token = [System.Environment]::GetEnvironmentVariable('GITHUB_TOKEN', 'User')
$headers = @{ Authorization = "Bearer $token"; Accept = "application/vnd.github+json" }
$runs = Invoke-RestMethod -Uri "https://api.github.com/repos/ConservationInternational/trends.earth/actions/runs?per_page=10" -Headers $headers
$failedRun = $runs.workflow_runs | Where-Object { $_.conclusion -eq 'failure' } | Select-Object -First 1

# 2. Get jobs for the failed run
$jobs = Invoke-RestMethod -Uri "https://api.github.com/repos/ConservationInternational/trends.earth/actions/runs/$($failedRun.id)/jobs" -Headers $headers
$failedJob = $jobs.jobs | Where-Object { $_.conclusion -eq 'failure' }

# 3. Get detailed logs
$logs = Invoke-RestMethod -Uri "https://api.github.com/repos/ConservationInternational/trends.earth/actions/jobs/$($failedJob.id)/logs" -Headers $headers
$logs | Select-String -Pattern "ERROR|FAIL" -Context 5,5
```

### Notes

- The GitHub token is stored in the User environment variable `GITHUB_TOKEN`
- Access it with: `[System.Environment]::GetEnvironmentVariable('GITHUB_TOKEN', 'User')`
- If the `GITHUB_TOKEN` environment variable is missing or invalid, prompt the user to configure it correctly before proceeding.
- The MCP server provides structured access to GitHub data, but direct API calls via PowerShell are more reliable for workflow logs
- Always check for artifacts when investigating test failures - they contain docker-compose logs and other debug information

## Repository Structure

This is the main Trends.Earth QGIS plugin repository. Key directories:

- `.github/workflows/` - CI/CD pipeline definitions
- `docker/` - Docker configuration for testing
- `LDMP/` - Main plugin code
- `test/` - Unit and integration tests

## Testing

### Local Testing
```bash
.\run_tests.ps1
```

### CI Testing
The CI runs tests on multiple QGIS versions (3.34, 3.36) using Docker containers.

Common failure points:
- QGIS 3.26 may have dependency compatibility issues (setuptools, packaging versions)
- Docker container startup failures often happen in `docker/trends-earth-test-pre-scripts.sh`
- Dependency installation issues with `trends.earth-schemas` from Git
