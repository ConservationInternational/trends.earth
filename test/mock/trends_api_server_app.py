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
    resp = {"access_token": sample_token}

    return json.dumps(resp)


@app.route("/api/v1/script/<script_id>/run", methods=["GET", "POST"])
def script_run(script_id):
    response = {}
    files = [
        DATA_PATH / "sample_raw_job.json",
    ]
    for f in files:
        with f.open() as fl:
            response = json.load(fl)
    return response


@app.route("/api/v1/script/<script_id>", methods=["GET", "POST"])
def script_index(script_id):
    response = {}
    files = [
        DATA_PATH / "sample_raw_job.json",
    ]
    for f in files:
        with f.open() as fl:
            response = json.load(fl)
    return response


@app.route("/api/v1/script", methods=["GET", "POST"])
def default_script():
    response = {}
    files = [
        DATA_PATH / "sample_raw_job.json",
    ]
    for f in files:
        with f.open() as fl:
            response = json.load(fl)
    return response
