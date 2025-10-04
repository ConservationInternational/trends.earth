# PowerShell Docker Test Runner for Trends.Earth QGIS Plugin
# 
# This script runs tests using Docker with the QGIS image, similar to the GitHub Actions workflow.
# It provides a Windows PowerShell equivalent to the bash-based Docker testing setup.
#
# Usage:
#   .\run_tests.ps1                    # Run all tests with cleanup
#   .\run_tests.ps1 -Verbose          # Run with verbose output
#   .\run_tests.ps1 -CleanUp:$false   # Leave containers running after tests
#
# Requirements:
#   - Docker Desktop installed and running
#   - Docker Compose available (included with Docker Desktop)
#   - Run from the trends.earth root directory

param(
    [string]$QgisVersion = "release-3_34",
    [string]$TestTarget = "test_suite.test_package",
    [switch]$Verbose = $false,
    [switch]$CleanUp = $true
)

Write-Host "========================================" -ForegroundColor Green
Write-Host "Trends.Earth Docker Test Runner" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "Running QGIS plugin tests in Docker environment" -ForegroundColor Cyan
Write-Host ""

# Check Docker availability
Write-Host "Checking Docker environment..." -ForegroundColor Yellow
try {
    docker --version
    if ($LASTEXITCODE -ne 0) {
        throw "Docker command failed"
    }
    Write-Host "✓ Docker is available" -ForegroundColor Green
} catch {
    Write-Error "Docker is not available. Please install Docker Desktop and ensure it's running."
    exit 1
}

# Check Docker Compose
$composeCmd = "docker-compose"
try {
    & docker-compose --version 2>$null
    if ($LASTEXITCODE -ne 0) {
        $composeCmd = "docker compose"
        & docker compose version
        if ($LASTEXITCODE -ne 0) {
            throw "Neither docker-compose nor docker compose work"
        }
    }
} catch {
    Write-Error "Docker Compose is not available. Please install Docker Desktop."
    exit 1
}

Write-Host "✓ Using Docker Compose: $composeCmd" -ForegroundColor Green

# Check required files
$requiredFiles = @("docker-compose.yml", ".env", "test_suite.py", "LDMP")
$missingFiles = @()
foreach ($file in $requiredFiles) {
    if (!(Test-Path $file)) {
        $missingFiles += $file
    }
}

if ($missingFiles.Count -gt 0) {
    Write-Error "Missing required files: $($missingFiles -join ', ')"
    Write-Error "Please run this script from the trends.earth root directory."
    exit 1
}

Write-Host "✓ Required files found" -ForegroundColor Green

# Setup Docker environment
Write-Host ""
Write-Host "========================================" -ForegroundColor Yellow
Write-Host "Preparing Docker Environment" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Yellow

# Normalize potential CRLF line endings in shell scripts executed inside container.
$scriptPaths = @('docker/qgis-testing-entrypoint.sh','docker/trends-earth-test-pre-scripts.sh')
foreach ($sp in $scriptPaths) {
    if (Test-Path $sp) {
        $raw = Get-Content $sp -Raw
        if ($raw -match "`r\n") {
            ($raw -replace "`r\n","`n") | Set-Content $sp -Encoding Ascii
            Write-Host "Normalized line endings: $sp" -ForegroundColor DarkGray
        }
    }
}

# Pull QGIS image
Write-Host "Pulling QGIS image ($QgisVersion) ..." -ForegroundColor Yellow
docker pull qgis/qgis:$QgisVersion
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to pull Docker image"
    exit 1
}
Write-Host "✓ Docker image ready" -ForegroundColor Green

# Clean up any existing containers
if ($CleanUp) {
    Write-Host "Cleaning up any existing containers..." -ForegroundColor Yellow
    & $composeCmd down 2>$null | Out-Null
}

# Write .env like CI (overwrites existing)
"QGIS_VERSION_TAG=$QgisVersion`nIMAGE=qgis/qgis`nON_TRAVIS=true`nMUTE_LOGS=true`nWITH_PYTHON_PEP=true" | Set-Content .env -Encoding UTF8

# Start Docker environment
Write-Host "Starting QGIS testing environment (full stack)..." -ForegroundColor Yellow
& $composeCmd up -d

if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to start Docker environment"
    exit 1
}

Write-Host "✓ Docker environment started" -ForegroundColor Green
Write-Host "Sleeping 60s to allow container initialization..." -ForegroundColor Yellow
Start-Sleep -Seconds 60

# Post-initialization container status check
$status = (& $composeCmd ps qgis-testing-environment 2>$null) -join "`n"
if (-not ($status -match 'Up') -or $status -match 'Exited') {
    Write-Error "Container exited during initialization. Capturing diagnostics..."
    Write-Host "---- docker compose ps ----" -ForegroundColor DarkGray
    try { & $composeCmd ps } catch { $null }
    Write-Host "---- container logs ----" -ForegroundColor DarkGray
    try { & $composeCmd logs qgis-testing-environment } catch { Write-Warning "Log retrieval failed: $($_.Exception.Message)" }
    Write-Host "---- entrypoint script (head) ----" -ForegroundColor DarkGray
    if (Test-Path docker/qgis-testing-entrypoint.sh) { Get-Content docker/qgis-testing-entrypoint.sh -TotalCount 40 }
    Write-Host "---- pre-script (head) ----" -ForegroundColor DarkGray
    if (Test-Path docker/trends-earth-test-pre-scripts.sh) { Get-Content docker/trends-earth-test-pre-scripts.sh -TotalCount 60 }
    if ($CleanUp) { & $composeCmd down -v | Out-Null }
    exit 1
}

Write-Host "Installing test dependencies (pytest, python-dotenv) ..." -ForegroundColor Yellow
& $composeCmd exec -T qgis-testing-environment sh -lc "if ! command -v pip3 >/dev/null 2>&1; then apt-get update && apt-get install -y --no-install-recommends python3-pip && rm -rf /var/lib/apt/lists/*; fi && python3 -m pip install --no-cache-dir -U pytest python-dotenv" | Out-Null

# Run the tests
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "Running Tests" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green

if ($Verbose) {
    Write-Host "Executing: qgis_testrunner.sh $TestTarget" -ForegroundColor Cyan
    Write-Host "Working directory: /tests_directory" -ForegroundColor Cyan
}

Write-Host "Running tests in QGIS Docker container..." -ForegroundColor Yellow
Write-Host ""

# Execute the tests (pass arguments separately, not as single string)
Write-Host "Running primary test attempt ($TestTarget)..." -ForegroundColor Yellow


# Preflight diagnostic to show Python, QGIS, GDAL versions (mirrors what CI logs expose)
if ($Verbose) {
    & $composeCmd exec -w /tests_directory qgis-testing-environment python3 -c "import qgis.core,osgeo.gdal as gdal,sys;print('QGIS',qgis.core.Qgis.QGIS_VERSION_INT,'GDAL',gdal.VersionInfo('RELEASE_NAME'),'Python',sys.version.split()[0])" 2>&1
}

& $composeCmd exec -T qgis-testing-environment sh -lc "qgis_testrunner.sh $TestTarget"
$exitCode = $LASTEXITCODE

Remove-Variable exitCode -ErrorAction SilentlyContinue
$exitCode = $LASTEXITCODE

# Display results
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "Test Results" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green

if ($exitCode -eq 0) { Write-Host "✓ Tests passed" -ForegroundColor Green } else { Write-Host "Tests failed with exit code $exitCode" -ForegroundColor Red }

# Cleanup
Write-Host ""
if ($CleanUp) { & $composeCmd down -v | Out-Null } else { Write-Host "(Leaving containers running)" -ForegroundColor Yellow }

exit $exitCode
