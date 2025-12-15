# coding=utf-8
"""Tests for layers.py round_to_n function.

This test reproduces and verifies the fix for the bug:
AttributeError: 'float' object has no attribute 'size'

.. note:: This program is free software; you can redistribute it and/or modify
     it under the terms of the GNU General Public License as published by
     the Free Software Foundation; either version 2 of the License, or
     (at your option) any later version.

"""

__author__ = "trends.earth"
__date__ = "2025/10/05"
__copyright__ = "Copyright 2025, Conservation International"

import unittest

import numpy as np

from LDMP.layers import round_to_n


class TestRoundToN(unittest.TestCase):
    """Test the round_to_n function in layers.py"""

    def test_python_float_input(self):
        """Test that round_to_n works with Python float (reproduces original bug)"""
        # This is the exact value from the error trace
        result = round_to_n(133.16005859375005, 2)
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 130.0, delta=5.0)

    def test_python_int_input(self):
        """Test that round_to_n works with Python int"""
        result = round_to_n(1234, 2)
        self.assertIsInstance(result, float)
        self.assertEqual(result, 1200.0)

    def test_zero_input(self):
        """Test that round_to_n returns 0 for zero input"""
        result = round_to_n(0, 2)
        self.assertEqual(result, 0)

    def test_zero_input_as_float(self):
        """Test that round_to_n returns 0 for zero float input"""
        result = round_to_n(0.0, 2)
        self.assertEqual(result, 0)

    def test_nan_input(self):
        """Test that round_to_n returns NaN for NaN input"""
        result = round_to_n(np.nan, 2)
        self.assertTrue(np.isnan(result))

    def test_small_float(self):
        """Test rounding small numbers"""
        result = round_to_n(0.00123, 3)
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 0.00123, places=5)

    def test_large_float(self):
        """Test rounding large numbers"""
        result = round_to_n(987654.321, 3)
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 988000.0, delta=1000.0)

    def test_negative_float(self):
        """Test rounding negative numbers (uses absolute value for log10)"""
        result = round_to_n(-456.789, 2)
        self.assertIsInstance(result, float)
        # The function uses abs() for log10, so it rounds based on magnitude
        self.assertAlmostEqual(result, -460.0, delta=5.0)

    def test_numpy_scalar_input(self):
        """Test that round_to_n works with numpy scalar (from .item())"""
        # This simulates cutoffs.item() from the original code
        numpy_scalar = np.array([133.16005859375005]).item()
        result = round_to_n(numpy_scalar, 2)
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 130.0, delta=5.0)

    def test_numpy_single_element_array(self):
        """Test that round_to_n works with single-element numpy array"""
        arr = np.array([123.456])
        result = round_to_n(arr, 2)
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 120.0, delta=5.0)

    def test_numpy_multi_element_array(self):
        """Test that round_to_n is not designed for multi-element arrays

        Note: The function is designed for scalar values and single-element arrays.
        Multi-element arrays are not used in the actual codebase.
        This test documents the current limitation.
        """
        arr = np.array([123.456, 234.567, 345.678])
        # This is expected to raise an error as it's not supported
        with self.assertRaises(ValueError):
            round_to_n(arr, 2)

    def test_different_significant_figures(self):
        """Test rounding with different numbers of significant figures"""
        value = 12345.6789

        result_1sf = round_to_n(value, 1)
        self.assertAlmostEqual(result_1sf, 10000.0, delta=1000.0)

        result_2sf = round_to_n(value, 2)
        self.assertAlmostEqual(result_2sf, 12000.0, delta=500.0)

        result_3sf = round_to_n(value, 3)
        self.assertAlmostEqual(result_3sf, 12300.0, delta=100.0)

        result_4sf = round_to_n(value, 4)
        self.assertAlmostEqual(result_4sf, 12350.0, delta=10.0)

    def test_edge_case_very_small_number(self):
        """Test with very small positive number"""
        result = round_to_n(1.23e-10, 2)
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0)
        self.assertLess(result, 1e-9)

    def test_edge_case_very_large_number(self):
        """Test with very large number"""
        result = round_to_n(1.23e10, 2)
        self.assertIsInstance(result, float)
        self.assertGreater(result, 1e10)
        self.assertLess(result, 2e10)

    def test_float_from_max_cutoff(self):
        """Test simulating the exact scenario from _get_cutoff function"""
        # Simulate: cutoffs.size == 2
        cutoffs = np.array([50.0, 133.16005859375005])
        max_cutoff = np.amax(np.absolute(cutoffs))
        # This should be a float
        result = round_to_n(float(max_cutoff), 2)
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 130.0, delta=5.0)

    def test_item_extraction_from_single_cutoff(self):
        """Test simulating cutoffs.item() scenario from _get_cutoff function"""
        # Simulate: cutoffs.size == 1
        cutoffs = np.array([133.16005859375005])
        # Extract using .item() which returns a Python scalar
        cutoff_value = cutoffs.item()
        result = round_to_n(cutoff_value, 2)
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 130.0, delta=5.0)


if __name__ == "__main__":
    unittest.main()
