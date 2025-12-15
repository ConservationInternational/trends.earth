import json
from pathlib import Path

from flask import Flask

app = Flask(__name__)

DATA_PATH = Path(__file__).parent / "data"
SCRIPTS_JSON_PATH = (
    Path(__file__).parent.parent.parent / "LDMP" / "data" / "scripts.json"
)

# Cache for script UUID mapping
_script_uuid_cache = None


def get_script_uuid_map():
    """
    Load script UUIDs from scripts.json and create a mapping.
    This allows the mock API to dynamically use current UUIDs without
    needing to manually sync the mock data files.
    """
    global _script_uuid_cache

    if _script_uuid_cache is None:
        _script_uuid_cache = {}
        try:
            with open(SCRIPTS_JSON_PATH, "r") as f:
                scripts = json.load(f)

            # Create mapping: script_name -> uuid and uuid -> script_name
            for script in scripts:
                script_name = script.get("name")
                script_id = script.get("id")

                if script_name and script_id:
                    _script_uuid_cache[script_name] = script_id
                    _script_uuid_cache[script_id] = script_name
        except Exception as e:
            print(f"Warning: Could not load scripts.json: {e}")

    return _script_uuid_cache


@app.route("/api/v1")
def index():
    catalog = DATA_PATH / "index.json"

    with catalog.open() as fl:
        return json.load(fl)


@app.route("/auth", methods=["POST"])
def auth():
    sample_token = "78euwd89"
    sample_refresh_token = "refresh_abc123def456"
    resp = {"access_token": sample_token, "refresh_token": sample_refresh_token}

    return json.dumps(resp)


@app.route("/auth/refresh", methods=["POST"])
def auth_refresh():
    sample_token = "new_access_token_xyz789"
    sample_refresh_token = "new_refresh_token_uvw123"
    resp = {"access_token": sample_token, "refresh_token": sample_refresh_token}

    return json.dumps(resp)


@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    resp = {"message": "Logged out successfully"}
    return json.dumps(resp)


@app.route("/api/v1/script/<script_id>/run", methods=["GET", "POST"])
def script_run(script_id):
    """
    Handle script run requests. Supports both UUID and script name lookups.
    Dynamically maps UUIDs from scripts.json to mock data entries.
    """
    response = {}
    uuid_map = get_script_uuid_map()

    # Check if script_id is a UUID that maps to a script name
    script_name = uuid_map.get(script_id, script_id)

    files = [
        DATA_PATH / "sample_raw_job.json",
    ]
    for f in files:
        with f.open() as fl:
            data = json.load(fl)
            # Try both the original script_id and the mapped script_name
            response = data.get(script_id, data.get(script_name, {}))

            # If we found a response, update any UUIDs in it to match current scripts.json
            if response and "data" in response:
                script_data = response["data"]
                if "script" in script_data and "name" in script_data["script"]:
                    current_script_name = script_data["script"]["name"]
                    current_uuid = uuid_map.get(current_script_name)

                    if current_uuid:
                        # Update script_id and script.id to match current UUID
                        script_data["script_id"] = current_uuid
                        script_data["script"]["id"] = current_uuid

            break

    return response


@app.route("/api/v1/script/<script_id>", methods=["GET", "POST"])
def script_index(script_id):
    """
    Handle script info requests. Supports both UUID and script name lookups.
    Dynamically maps UUIDs from scripts.json to mock data entries.
    """
    response = {}
    uuid_map = get_script_uuid_map()

    # Check if script_id is a UUID that maps to a script name
    script_name = uuid_map.get(script_id, script_id)

    files = [
        DATA_PATH / "sample_raw_job.json",
    ]
    for f in files:
        with f.open() as fl:
            data = json.load(fl)
            # Try both the original script_id and the mapped script_name
            response = data.get(script_id, data.get(script_name, {}))

            # If we found a response, update any UUIDs in it to match current scripts.json
            if response and "data" in response:
                script_data = response["data"]
                if "script" in script_data and "name" in script_data["script"]:
                    current_script_name = script_data["script"]["name"]
                    current_uuid = uuid_map.get(current_script_name)

                    if current_uuid:
                        # Update script_id and script.id to match current UUID
                        script_data["script_id"] = current_uuid
                        script_data["script"]["id"] = current_uuid

            break

    return response


@app.route("/api/v1/script", methods=["GET", "POST"])
def default_script():
    response = {}
    files = [
        DATA_PATH / "sample_raw_job.json",
    ]
    for f in files:
        with f.open() as fl:
            data = json.load(fl)
            response = data
    return response
