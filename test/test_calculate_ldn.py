"""
/***************************************************************************
 LDMP - A QGIS plugin
 This plugin supports monitoring and reporting of land degradation to the UNCCD
 and in support of the SDG Land Degradation Neutrality (LDN) target.
                              -------------------
        begin                : 2017-05-23
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Conservation International
        email                : trends.earth@conservation.org
 ***************************************************************************/
"""

import datetime
import json
import unittest
import uuid
from multiprocessing import Process
from pathlib import Path
from unittest.mock import patch

from mock.mock_http_server import MockApiServer
from qgis.core import QgsApplication, QgsAuthMethodConfig
from qgis.PyQt import QtCore
from te_schemas.jobs import JobStatus
from te_schemas.results import (
    URI,
    Band,
    DataType,
    Raster,
    RasterFileType,
    RasterResults,
)

from LDMP.api import APIClient
from LDMP.auth import AuthSetup
from LDMP.conf import KNOWN_SCRIPTS
from LDMP.jobs.manager import job_manager
from LDMP.jobs.models import Job
from LDMP.localexecution.ldn import compute_ldn_subnational


def _minimal_geojson():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [0.0, 0.0],
                            [0.0, 1.0],
                            [1.0, 1.0],
                            [1.0, 0.0],
                            [0.0, 0.0],
                        ]
                    ],
                },
            }
        ],
    }


class CalculateLDNOneStep(unittest.TestCase):
    def setUp(self):
        self.app_server = MockApiServer()

        self.server = Process(target=self.app_server.run)
        self.server.start()

        # Wait for server to be ready before continuing
        if not self.app_server.wait_until_ready(timeout=10):
            raise RuntimeError("Mock API server failed to start within timeout")

        self.api_client = APIClient(self.app_server.url, 30)
        self.response = None
        self.error = None

    def set_auth_db(self):
        AUTHDB_MASTERPWD = "password"
        print("Init script: %s" % __file__)

        auth_manager = QgsApplication.authManager()
        if not auth_manager.masterPasswordHashInDatabase():
            auth_manager.setMasterPassword(AUTHDB_MASTERPWD, True)
            # Create config
            auth_manager.authenticationDatabasePath()
            auth_manager.masterPasswordIsSet()

        auth_setup = AuthSetup(name="Trends.Earth")

        cfg = QgsAuthMethodConfig()
        cfg.setName(auth_setup.name)
        cfg.setMethod("Basic")
        cfg.setConfig("username", "test")
        cfg.setConfig("password", "test")
        auth_manager.storeAuthenticationConfig(cfg)

        QtCore.QSettings().setValue(f"trends_earth/{auth_setup.key}", cfg.id())

        return cfg.id()

    def test_job_submission(self):
        ldn_one_step_script_name = "sdg-15-3-1-sub-indicators"

        script = [
            s for s in KNOWN_SCRIPTS.values() if s.name == ldn_one_step_script_name
        ][0]

        self.auth_id = self.set_auth_db()

        job_manager.api_client = self.api_client
        job_dict = {"task_notes": "Test"}

        response = job_manager.submit_remote_job(job_dict, script.id)

        self.assertIsNotNone(response)
        if isinstance(response, Job):
            self.assertIsNotNone(response.get_display_name())
        else:
            self.assertIsNotNone(response["data"])

    def tearDown(self):
        self.server.terminate()
        self.server.join()


class CalculateLDNSubnationalSerialization(unittest.TestCase):
    def test_subnational_results_are_job_serializable(self):
        script = [
            s for s in KNOWN_SCRIPTS.values() if s.name == "sdg-15-3-1-sub-indicators"
        ][0]
        job = Job(
            id=uuid.uuid4(),
            params={
                "subnational_units": [
                    {
                        "unit_id": "unit-1",
                        "unit_name": "Unit 1",
                        "geojson": _minimal_geojson(),
                    },
                    {
                        "unit_id": "unit-2",
                        "unit_name": "Unit 2",
                        "geojson": _minimal_geojson(),
                    },
                ]
            },
            progress=0,
            start_date=datetime.datetime.now(datetime.timezone.utc),
            status=JobStatus.PENDING,
            task_name="SDG Indicator",
            task_notes="subnational test",
            script=script,
        )

        def _fake_compute_ldn(
            unit_job,
            unit_aoi,
            unit_output_path,
            dataset_output_path,
            progress_callback,
            killed_callback,
        ):
            return RasterResults(
                name="land_condition_summary",
                uri=URI(uri=unit_output_path.with_suffix(".vrt")),
                rasters={
                    DataType.INT16.value: Raster(
                        uri=URI(uri=unit_output_path.with_suffix(".vrt")),
                        bands=[
                            Band(
                                name="SDG 15.3.1 Indicator",
                                metadata={},
                                no_data_value=-32768,
                                activated=True,
                                add_to_map=True,
                            )
                        ],
                        datatype=DataType.INT16,
                        filetype=RasterFileType.COG,
                    )
                },
                data={"report": {"ok": True}},
            )

        with patch(
            "LDMP.localexecution.ldn.compute_ldn", side_effect=_fake_compute_ldn
        ):
            results = compute_ldn_subnational(
                job,
                Path("/tmp/test_job.json"),
                Path("/tmp/test_dataset.tif"),
                None,
                None,
            )

        self.assertEqual(len(results), 2)
        self.assertTrue(all(isinstance(result, RasterResults) for result in results))
        self.assertEqual(
            [result.data["subnational_unit"]["unit_id"] for result in results],
            ["unit-1", "unit-2"],
        )
        self.assertIn("Unit 1", results[0].name)
        self.assertIn("Unit 2", results[1].name)

        job.results = results
        dumped = Job.Schema().dump(job)
        encoded = json.dumps(dumped)
        self.assertIn("RasterResults", encoded)
        self.assertIn("subnational_unit", encoded)


if __name__ == "__main__":
    unittest.main()
