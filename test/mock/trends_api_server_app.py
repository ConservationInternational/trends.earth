import json

from pathlib import Path

from flask import Flask, request

app = Flask(__name__)

DATA_PATH = Path(__file__).parent / "data"


@app.route("/api/v1")
def index():
    catalog = DATA_PATH / "algorithm_response.json"

    with catalog.open() as fl:
        return json.load(fl)

@app.route("/auth", methods=['POST'])
def auth():
    sample_token = '78euwd89'
    print("SAMPLE TOKEN")
    print(sample_token)
    return {"access_token": sample_token}


@app.route("/api/v1/script/<script_id>/run", methods=['GET', 'POST'])
def script_run(script_id):
    print("log script_id")

    print(script_id)

    response = {}
    files = [
        DATA_PATH / "response.json",
    ]
    for f in files:
        with f.open() as fl:
            item = json.load(fl)
            response["data"] = item
    return response

