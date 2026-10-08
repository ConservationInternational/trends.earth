import unittest
from unittest.mock import Mock

from LDMP.data_io import DlgDataIOImportPopulation


class ImportPopulationTests(unittest.TestCase):
    def test_population_type_defaults_to_total(self):
        dialog = Mock()
        dialog.radio_population_male.isChecked.return_value = False
        dialog.radio_population_female.isChecked.return_value = False

        population_type = DlgDataIOImportPopulation._population_type(dialog)

        self.assertEqual(population_type, "total")

    def test_population_type_returns_male(self):
        dialog = Mock()
        dialog.radio_population_male.isChecked.return_value = True

        population_type = DlgDataIOImportPopulation._population_type(dialog)

        self.assertEqual(population_type, "male")

    def test_population_type_returns_female(self):
        dialog = Mock()
        dialog.radio_population_male.isChecked.return_value = False
        dialog.radio_population_female.isChecked.return_value = True

        population_type = DlgDataIOImportPopulation._population_type(dialog)

        self.assertEqual(population_type, "female")
