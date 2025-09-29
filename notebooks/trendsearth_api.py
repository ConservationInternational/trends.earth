"""
Trends.Earth API Client Module

This module provides common functionality for authenticating with and making requests
to the Trends.Earth API. It can be shared across multiple notebooks to avoid code duplication.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import requests


class TrendsEarthAPIClient:
    """
    A client for interacting with the Trends.Earth API.

    This class handles authentication, job submission, monitoring, and data retrieval
    from the Trends.Earth API.
    """

    def __init__(self, api_url: str = "https://api.trends.earth"):
        """
        Initialize the API client.

        Args:
            api_url: Base URL for the Trends.Earth API
        """
        self.api_url = api_url.rstrip("/")
        self.session = requests.Session()
        self.access_token = None
        self.refresh_token = None
        self.token_expires_at = None

    def authenticate_from_env(self) -> bool:
        """
        Authenticate using credentials from environment variables.

        Expected environment variables:
        - API_USERNAME: API username/email
        - API_PASSWORD: API password
        - API_BASE_URL: API base URL (optional, overrides constructor)

        Returns:
            True if authentication successful, False otherwise
        """
        try:
            username = os.getenv("API_USERNAME")
            password = os.getenv("API_PASSWORD")
            base_url = os.getenv("API_BASE_URL")

            if not username or not password:
                print("Missing API credentials in environment variables")
                print("Please set the following environment variables:")
                print("- API_USERNAME: Your API username/email")
                print("- API_PASSWORD: Your API password")
                print("- API_BASE_URL: API base URL (optional)")
                return False

            # Update API URL if provided in environment
            if base_url:
                self.api_url = base_url.rstrip("/")
                print(f"Using API URL from environment: {self.api_url}")

            return self.authenticate(username, password)

        except Exception as e:
            logging.error(f"Error loading environment credentials: {e}")
            return False

    def authenticate(self, email: str, password: str) -> bool:
        """
        Authenticate with the Trends.Earth API using email and password.

        Args:
            email: User email address
            password: User password

        Returns:
            True if authentication successful, False otherwise
        """
        if not email or not password:
            print("Cannot authenticate: Missing email or password")
            return False

        auth_url = f"{self.api_url}/auth"
        auth_data = {"email": email, "password": password}

        try:
            print("Authenticating with Trends.Earth API...")
            print(f"   Using email: {email}")

            response = self.session.post(auth_url, json=auth_data)

            if response.status_code == 200:
                auth_result = response.json()
                self.access_token = auth_result.get("access_token")
                self.refresh_token = auth_result.get("refresh_token")

                # Calculate token expiration time if provided
                expires_in = auth_result.get("expires_in")  # usually in seconds
                if expires_in:
                    self.token_expires_at = datetime.now(timezone.utc) + timedelta(
                        seconds=expires_in
                    )
                else:
                    # Default to 1 hour if not provided
                    self.token_expires_at = datetime.now(timezone.utc) + timedelta(
                        hours=1
                    )

                if self.access_token:
                    # Set authorization header for future requests
                    self.session.headers.update(
                        {
                            "Authorization": f"Bearer {self.access_token}",
                            "Content-Type": "application/json",
                        }
                    )
                    print("Successfully authenticated with Trends.Earth API")
                    logging.info("Successfully authenticated with Trends.Earth API")
                    return True
                else:
                    print("No access token received")
                    print(f"Response: {auth_result}")
                    return False
            else:
                print(f"Authentication failed: {response.status_code}")
                print(f"Response: {response.text}")
                logging.error(f"Authentication failed: {response.status_code}")
                return False

        except Exception as e:
            print(f"Authentication error: {str(e)}")
            logging.error(f"Error authenticating: {e}")
            return False

    def is_token_expired(self) -> bool:
        """
        Check if the current access token is expired or about to expire.

        Returns:
            True if token is expired or will expire within 5 minutes, False otherwise
        """
        if not self.token_expires_at:
            return False

        # Consider token expired if it expires within 5 minutes
        buffer_time = timedelta(minutes=5)
        return datetime.now(timezone.utc) >= (self.token_expires_at - buffer_time)

    def refresh_access_token(self) -> bool:
        """
        Refresh the access token using the refresh token.

        Returns:
            True if refresh successful, False otherwise
        """
        if not self.refresh_token:
            print("No refresh token available")
            return False

        refresh_url = f"{self.api_url}/auth/refresh"
        refresh_data = {"refresh_token": self.refresh_token}

        try:
            print("Refreshing access token...")

            response = self.session.post(refresh_url, json=refresh_data)

            if response.status_code == 200:
                auth_result = response.json()
                self.access_token = auth_result.get("access_token")

                # Update refresh token if a new one is provided
                new_refresh_token = auth_result.get("refresh_token")
                if new_refresh_token:
                    self.refresh_token = new_refresh_token

                # Update token expiration time
                expires_in = auth_result.get("expires_in")
                if expires_in:
                    self.token_expires_at = datetime.now(timezone.utc) + timedelta(
                        seconds=expires_in
                    )
                else:
                    # Default to 1 hour if not provided
                    self.token_expires_at = datetime.now(timezone.utc) + timedelta(
                        hours=1
                    )

                if self.access_token:
                    # Update authorization header
                    self.session.headers.update(
                        {
                            "Authorization": f"Bearer {self.access_token}",
                            "Content-Type": "application/json",
                        }
                    )
                    print("Successfully refreshed access token")
                    logging.info("Successfully refreshed access token")
                    return True
                else:
                    print("No access token received from refresh")
                    return False
            else:
                print(f"Token refresh failed: {response.status_code}")
                print(f"Response: {response.text}")
                logging.error(f"Token refresh failed: {response.status_code}")
                return False

        except Exception as e:
            print(f"Token refresh error: {str(e)}")
            logging.error(f"Error refreshing token: {e}")
            return False

    def ensure_valid_token(self) -> bool:
        """
        Ensure we have a valid access token, refreshing if necessary.

        Returns:
            True if we have a valid token, False otherwise
        """
        if not self.access_token:
            print("No access token available")
            return False

        if self.is_token_expired():
            print("Access token expired, attempting to refresh...")
            if not self.refresh_access_token():
                print("Failed to refresh token, re-authentication required")
                return False

        return True

    def get_auth_headers(self) -> Optional[Dict[str, str]]:
        """
        Get authentication headers for API requests.

        Returns:
            Dictionary with authorization headers, or None if not authenticated
        """
        if self.ensure_valid_token():
            return {
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            }
        return None

    def submit_job(self, script_endpoint: str, params: Dict) -> Optional[str]:
        """
        Generic method to submit a job to any script endpoint.

        Args:
            script_endpoint: The script endpoint path (e.g., "sdg-15-3-1-indicator-2-1-17")
            params: Parameters for the job

        Returns:
            Job ID if successful, None otherwise
        """
        if not self.ensure_valid_token():
            return None

        script_url = f"{self.api_url}/api/v1/script/{script_endpoint}/run"

        try:
            response = self.session.post(script_url, json=params, timeout=60)

            # Check if we got a 401 and try to refresh token
            if response.status_code == 401 and self.refresh_token:
                print("Received 401, attempting token refresh...")
                if self.refresh_access_token():
                    # Retry the request with refreshed token
                    response = self.session.post(script_url, json=params, timeout=60)

            if response.status_code == 200:
                job_data = response.json()
                job_id = job_data.get("data", {}).get("id")
                if job_id:
                    logging.info(f"Job submitted successfully (ID: {job_id})")
                    return job_id
                else:
                    print("No job ID returned from API")
                    return None
            else:
                logging.error(
                    f"Job submission failed: {response.status_code} - {response.text}"
                )
                print(
                    f"Job submission failed: {response.status_code} - {response.text}"
                )
                return None

        except Exception as e:
            logging.error(f"Error submitting job: {e}")
            print(f"Error submitting job: {e}")
            return None

    def get_jobs(
        self, filter_name: Optional[str] = None, days_back: int = 7
    ) -> List[Dict]:
        """
        Get jobs from the API, optionally filtered by name and date.

        Args:
            filter_name: Optional filter for job names
            days_back: Number of days to look back for jobs

        Returns:
            List of job dictionaries
        """
        if not self.ensure_valid_token():
            return []

        try:
            # Calculate date filter
            now = datetime.now(tz=timezone.utc)
            relevant_date = now - timedelta(days=days_back)

            # Get jobs from API
            response = self.session.get(
                f"{self.api_url}/api/v1/execution",
                params={"updated_at": relevant_date.strftime("%Y-%m-%d")},
                timeout=30,
            )

            # Check if we got a 401 and try to refresh token
            if response.status_code == 401 and self.refresh_token:
                print("Received 401, attempting token refresh...")
                if self.refresh_access_token():
                    # Retry the request with refreshed token
                    response = self.session.get(
                        f"{self.api_url}/api/v1/execution",
                        params={"updated_at": relevant_date.strftime("%Y-%m-%d")},
                        timeout=30,
                    )

            if response.status_code == 200:
                jobs = response.json()["data"]

                # Filter by name if specified
                if filter_name:
                    jobs = [
                        job
                        for job in jobs
                        if filter_name in job.get("params", {}).get("task_name", "")
                    ]

                return jobs
            else:
                logging.error(f"Failed to get jobs: {response.status_code}")
                return []

        except Exception as e:
            logging.error(f"Error getting jobs: {e}")
            return []

    def get_job_status(self, execution_id: str) -> Optional[Dict]:
        """
        Get the status of a specific job.

        Args:
            execution_id: ID of the execution to check

        Returns:
            Job status dictionary, or None if not found
        """
        if not self.ensure_valid_token():
            return None

        try:
            response = self.session.get(
                f"{self.api_url}/api/v1/execution/{execution_id}", timeout=30
            )

            # Check if we got a 401 and try to refresh token
            if response.status_code == 401 and self.refresh_token:
                print("Received 401, attempting token refresh...")
                if self.refresh_access_token():
                    # Retry the request with refreshed token
                    response = self.session.get(
                        f"{self.api_url}/api/v1/execution/{execution_id}", timeout=30
                    )

            if response.status_code == 200:
                return response.json().get("data")
            else:
                print(f"Failed to get job status: {response.status_code}")
                return None

        except Exception as e:
            print(f"Error getting job status: {e}")
            return None

    def monitor_job(self, execution_id: str, max_minutes: int = 10) -> Optional[Dict]:
        """
        Monitor a job until completion or timeout.

        Args:
            execution_id: ID of the execution to monitor
            max_minutes: Maximum time to wait in minutes

        Returns:
            Final job status dictionary, or None if timeout/error
        """
        start_time = time.time()

        while True:
            job_data = self.get_job_status(execution_id)
            if not job_data:
                return None

            status = job_data.get("status", "unknown").upper()
            print(f"Status: {status}")

            if status in ["SUCCESS", "FINISHED"]:
                print("Job completed successfully!")
                return job_data
            elif status in ["FAILED", "ERROR"]:
                print("Job failed!")
                return job_data
            elif status in ["CANCELLED", "CANCELED"]:
                print("Job was cancelled!")
                return job_data

            # Check timeout
            elapsed_minutes = (time.time() - start_time) / 60
            if elapsed_minutes >= max_minutes:
                print(f"Monitoring timeout after {max_minutes} minutes")
                return job_data

            # Wait before next check
            time.sleep(30)

    def download_job(
        self, job_dict: Dict, output_dir: Union[str, Path]
    ) -> Optional[Path]:
        """
        Download a completed job's results.

        Args:
            job_dict: Job dictionary from API
            output_dir: Directory to save downloaded files

        Returns:
            Path to downloaded files directory, or None if failed
        """
        if not self.ensure_valid_token():
            return None

        job_id = job_dict.get("id")
        task_name = job_dict.get("params", {}).get("task_name", "unknown")

        if not job_id:
            print("Job ID not found in job dictionary")
            return None

        # Create output directory
        output_dir = Path(output_dir)
        job_dir = output_dir / f"{task_name}_{job_id}"
        job_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Download job data
            response = self.session.get(
                f"{self.api_url}/api/v1/download/{job_id}",
                timeout=300,  # 5 minutes timeout for downloads
            )

            # Check if we got a 401 and try to refresh token
            if response.status_code == 401 and self.refresh_token:
                print("Received 401, attempting token refresh...")
                if self.refresh_access_token():
                    # Retry the request with refreshed token
                    response = self.session.get(
                        f"{self.api_url}/api/v1/download/{job_id}",
                        timeout=300,  # 5 minutes timeout for downloads
                    )

            if response.status_code == 200:
                # Save the downloaded content
                download_file = job_dir / f"{task_name}_{job_id}.zip"
                with open(download_file, "wb") as f:
                    f.write(response.content)

                print(f"Downloaded: {download_file}")

                # Save job metadata
                metadata_file = job_dir / "job_metadata.json"
                save_job_metadata(job_dict, metadata_file)

                return job_dir
            else:
                print(f"Download failed: {response.status_code}")
                return None

        except Exception as e:
            print(f"Error downloading job: {e}")
            return None


def print_job_summary(jobs: List[Dict]) -> None:
    """
    Print a summary of jobs by status.

    Args:
        jobs: List of job dictionaries
    """
    if not jobs:
        print("No jobs found")
        return

    # Count by status
    status_counts = {}
    for job in jobs:
        status = job.get("status", "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1

    print(f"Job Summary ({len(jobs)} total):")
    for status, count in sorted(status_counts.items()):
        status_indicators = {
            "FINISHED": "[DONE]",
            "RUNNING": "[RUNNING]",
            "PENDING": "[PENDING]",
            "FAILED": "[FAILED]",
            "READY": "[READY]",
        }
        indicator = status_indicators.get(status, "[UNKNOWN]")
        print(f"   {indicator} {status}: {count}")


def print_job_details(
    jobs: List[Dict], max_jobs: int = 20, local_tz: Any = None
) -> None:
    """
    Print detailed job information.

    Args:
        jobs: List of job dictionaries
        max_jobs: Maximum number of jobs to display
        local_tz: Local timezone for date formatting (optional)
    """
    if not jobs:
        return

    print(f"\nJob Details (showing up to {max_jobs}):")

    for i, job in enumerate(jobs[:max_jobs]):
        task_name = job.get("params", {}).get("task_name", "Unknown")
        status = job.get("status", "Unknown")

        start_date = datetime.fromisoformat(job["start_date"].replace("Z", "+00:00"))
        if local_tz:
            start_str = start_date.astimezone(local_tz).strftime("%b %d - %I:%M %p")
        else:
            start_str = start_date.strftime("%b %d - %I:%M %p UTC")

        if job.get("end_date"):
            end_date = datetime.fromisoformat(job["end_date"].replace("Z", "+00:00"))
            if local_tz:
                end_str = end_date.astimezone(local_tz).strftime("%b %d - %I:%M %p")
            else:
                end_str = end_date.strftime("%b %d - %I:%M %p UTC")
        else:
            end_str = "N/A"

        print(
            f"   {i + 1:2d}. {task_name[:30]:<30} | {status:<10} | {start_str} → {end_str}"
        )


def save_job_metadata(job_dict: Dict, output_path: Union[str, Path]) -> None:
    """
    Save job metadata to a JSON file.

    Args:
        job_dict: Job dictionary from API
        output_path: Path to save the metadata file
    """
    try:
        with open(output_path, "w") as f:
            json.dump(job_dict, f, indent=2, default=str)
        print(f"Saved metadata: {output_path}")
    except Exception as e:
        print(f"Error saving metadata: {e}")


def get_tiff_files(file_list: List[Path]) -> Tuple[List[Path], List[Path]]:
    """
    Filter files to find TIFF files.

    Args:
        file_list: List of file paths to filter

    Returns:
        Tuple of (all_files, tiff_files) where tiff_files are the .tif/.tiff files
    """
    tiff_files = []
    for file_path in file_list:
        if file_path.suffix.lower() in [".tif", ".tiff"]:
            tiff_files.append(file_path)

    return file_list, tiff_files


def convert_subcells_to_geojson(sub_cells) -> List[Dict]:
    """
    Convert shapely polygons to geojson format.

    Args:
        sub_cells: List of shapely polygon objects

    Returns:
        List of GeoJSON dictionaries
    """
    from shapely.geometry import mapping

    geojsons = []
    for sub_cell in sub_cells:
        geojson = json.loads(json.dumps(mapping(sub_cell)))
        geojsons.append(geojson)
    return geojsons
