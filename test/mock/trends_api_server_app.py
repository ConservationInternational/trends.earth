import json
from pathlib import Path

from flask import Flask

app = Flask(__name__)

DATA_PATH = Path(__file__).parent / "data"


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
    response = {}
    files = [
        DATA_PATH / "sample_raw_job.json",
    ]
    for f in files:
        with f.open() as fl:
            data = json.load(fl)
            response = data.get(script_id, {})
    return response


@app.route("/api/v1/script/<script_id>", methods=["GET", "POST"])
def script_index(script_id):
    response = {}
    files = [
        DATA_PATH / "sample_raw_job.json",
    ]
    for f in files:
        with f.open() as fl:
            data = json.load(fl)
            response = data.get(script_id, {})
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
