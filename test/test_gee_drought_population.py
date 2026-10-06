import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from te_schemas.results import DataType


class TestDroughtPopulationExport(unittest.TestCase):
    def test_population_export_is_float32_with_explicit_nodata(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "gee"
            / "drought-vulnerability"
            / "src"
            / "main.py"
        )
        spec = importlib.util.spec_from_file_location("drought_gee", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        collection = MagicMock()
        collection.select.return_value = collection
        image = collection.toBands.return_value
        image.rename.return_value = image
        image.addBands.return_value = image
        image.unmask.return_value = image
        image.float.return_value = image

        with patch.object(module, "_wp_filter_date", return_value=collection):
            result = module._get_population(
                2020, {"asset": "worldpop", "source": "WorldPop"}, MagicMock(), True
            )

        image.unmask.assert_called_once_with(-32768)
        image.float.assert_called_once_with()
        image.int16.assert_not_called()
        self.assertIs(result["image"], image)
        self.assertEqual(result["datatype"], DataType.FLOAT32)
        self.assertEqual(len(result["bands"]), 2)
        for band, pop_type in zip(result["bands"], ("male", "female")):
            self.assertEqual(band.no_data_value, -32768)
            self.assertEqual(band.metadata["type"], pop_type)
            self.assertEqual(band.metadata["year"], 2020)
            self.assertTrue(band.add_to_map)
