# coding=utf-8
"""Tests for layers.py styling functions with edge case data.

This test suite verifies that styling functions handle edge cases correctly:
- All no-data values
- Single unique value
- All zeros
- Mixed edge cases

.. note:: This program is free software; you can redistribute it and/or modify
     it under the terms of the GNU General Public License as published by
     the Free Software Foundation; either version 2 of the License, or
     (at your option) any later version.

"""

__author__ = "trends.earth"
__date__ = "2025/10/06"
__copyright__ = "Copyright 2025, Conservation International"

import unittest

import numpy as np

from LDMP.layers import _get_cutoff, round_to_n


class TestGetCutoffEdgeCases(unittest.TestCase):
    """Test the _get_cutoff function with edge case data"""

    def test_all_no_data_values(self):
        """Test that _get_cutoff handles all no-data values correctly"""
        # Create array with all no-data values
        data_sample = np.full((100, 100), -32768.0)
        no_data_value = -32768
        percentiles = [98]

        result = _get_cutoff(data_sample, no_data_value, percentiles, mask_zeros=False)

        # Should return 0 when all values are no data
        self.assertEqual(result, 0)

    def test_all_no_data_values_with_zero_masking(self):
        """Test _get_cutoff with all no-data and mask_zeros=True"""
        data_sample = np.full((100, 100), -32768.0)
        no_data_value = -32768
        percentiles = [98]

        result = _get_cutoff(data_sample, no_data_value, percentiles, mask_zeros=True)

        self.assertEqual(result, 0)

    def test_single_unique_value(self):
        """Test that _get_cutoff handles single unique value correctly"""
        # Create array with all same value
        data_sample = np.full((100, 100), 42.5)
        no_data_value = -32768
        percentiles = [98]

        result = _get_cutoff(data_sample, no_data_value, percentiles, mask_zeros=False)

        # Should return the rounded value
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0)
        self.assertAlmostEqual(result, 43.0, delta=1.0)

    def test_all_zeros_without_masking(self):
        """Test _get_cutoff with all zeros and mask_zeros=False"""
        data_sample = np.zeros((100, 100))
        no_data_value = -32768
        percentiles = [98]

        result = _get_cutoff(data_sample, no_data_value, percentiles, mask_zeros=False)

        # Without masking, should handle zeros
        self.assertEqual(result, 0)

    def test_all_zeros_with_masking(self):
        """Test _get_cutoff with all zeros and mask_zeros=True"""
        data_sample = np.zeros((100, 100))
        no_data_value = -32768
        percentiles = [98]

        result = _get_cutoff(data_sample, no_data_value, percentiles, mask_zeros=True)

        # With masking, all zeros are masked out
        self.assertEqual(result, 0)

    def test_mostly_no_data_with_few_valid_values(self):
        """Test _get_cutoff with mostly no-data and few valid values"""
        # Create array mostly no-data with a few valid values
        data_sample = np.full((100, 100), -32768.0)
        data_sample[50:55, 50:55] = 100.0  # Small patch of valid data
        no_data_value = -32768
        percentiles = [98]

        result = _get_cutoff(data_sample, no_data_value, percentiles, mask_zeros=False)

        # Should return cutoff based on valid values
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0)

    def test_two_percentiles_all_no_data(self):
        """Test _get_cutoff with two percentiles and all no-data"""
        data_sample = np.full((100, 100), -32768.0)
        no_data_value = -32768
        percentiles = [2, 98]  # For zero-centered stretch

        result = _get_cutoff(data_sample, no_data_value, percentiles, mask_zeros=True)

        self.assertEqual(result, 0)

    def test_two_percentiles_single_value(self):
        """Test _get_cutoff with two percentiles and single unique value"""
        data_sample = np.full((100, 100), 50.0)
        no_data_value = -32768
        percentiles = [2, 98]

        result = _get_cutoff(data_sample, no_data_value, percentiles, mask_zeros=True)

        # Should return rounded value
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0)

    def test_mixed_no_data_zeros_and_values(self):
        """Test _get_cutoff with mixed no-data, zeros, and valid values"""
        data_sample = np.full((100, 100), -32768.0)
        data_sample[0:30, 0:30] = 0.0  # Some zeros
        data_sample[30:40, 30:40] = 75.0  # Some valid values
        no_data_value = -32768
        percentiles = [98]

        result = _get_cutoff(data_sample, no_data_value, percentiles, mask_zeros=True)

        # Should compute based on valid non-zero values
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0)

    def test_negative_values_only(self):
        """Test _get_cutoff with only negative values"""
        data_sample = np.full((100, 100), -50.0)
        no_data_value = -32768
        percentiles = [98]

        result = _get_cutoff(data_sample, no_data_value, percentiles, mask_zeros=False)

        # Negative cutoffs return 0
        self.assertEqual(result, 0)

    def test_two_percentiles_all_negative(self):
        """Test _get_cutoff with two percentiles and all negative values"""
        data_sample = np.full((100, 100), -50.0)
        no_data_value = -32768
        percentiles = [2, 98]

        result = _get_cutoff(data_sample, no_data_value, percentiles, mask_zeros=False)

        # Should use absolute value and return positive
        self.assertIsInstance(result, float)
        self.assertGreaterEqual(result, 0)

    def test_very_small_values(self):
        """Test _get_cutoff with very small positive values"""
        data_sample = np.full((100, 100), 0.00001)
        no_data_value = -32768
        percentiles = [98]

        result = _get_cutoff(data_sample, no_data_value, percentiles, mask_zeros=True)

        # Should handle small values correctly
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0)
        self.assertLess(result, 1)

    def test_very_large_values(self):
        """Test _get_cutoff with very large values"""
        data_sample = np.full((100, 100), 999999.9)
        no_data_value = -32768
        percentiles = [98]

        result = _get_cutoff(data_sample, no_data_value, percentiles, mask_zeros=False)

        # Should handle large values correctly
        self.assertIsInstance(result, float)
        self.assertGreater(result, 1000)

    def test_single_valid_pixel(self):
        """Test _get_cutoff with only one valid pixel"""
        data_sample = np.full((100, 100), -32768.0)
        data_sample[50, 50] = 123.456
        no_data_value = -32768
        percentiles = [98]

        result = _get_cutoff(data_sample, no_data_value, percentiles, mask_zeros=False)

        # Should return rounded value of the single pixel
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0)
        self.assertAlmostEqual(result, 120.0, delta=10.0)

    def test_nan_values_mixed_with_data(self):
        """Test _get_cutoff with NaN values mixed with valid data"""
        data_sample = np.full((100, 100), np.nan)
        data_sample[40:60, 40:60] = 85.0  # Some valid values
        no_data_value = -32768
        percentiles = [98]

        result = _get_cutoff(data_sample, no_data_value, percentiles, mask_zeros=False)

        # Should handle NaN values and compute from valid data
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0)


class TestColorRampEdgeCases(unittest.TestCase):
    """Test color ramp creation with edge case data

    Note: These tests focus on data handling rather than QGIS-specific
    color ramp objects, since QGIS objects require the full QGIS environment.
    """

    def test_round_to_n_with_cutoff_zero(self):
        """Test that round_to_n handles zero cutoff correctly"""
        # This can happen when all data is no-data or negative
        result = round_to_n(0, 2)
        self.assertEqual(result, 0)

    def test_round_to_n_with_very_small_cutoff(self):
        """Test that round_to_n handles very small cutoffs"""
        result = round_to_n(0.0001, 2)
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0)

    def test_round_to_n_with_single_value_cutoff(self):
        """Test round_to_n with typical single-value scenario"""
        # When all pixels have same value, cutoff is that value
        result = round_to_n(42.5, 2)
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 43.0, delta=1.0)


class TestDataSampleGeneration(unittest.TestCase):
    """Test that various data patterns are handled correctly"""

    def test_empty_array_handling(self):
        """Test _get_cutoff with empty array after masking"""
        # Create array where everything gets masked
        data_sample = np.full((10, 10), -32768.0)
        no_data_value = -32768
        percentiles = [98]

        result = _get_cutoff(data_sample, no_data_value, percentiles, mask_zeros=False)

        # Should return 0 for empty masked array
        self.assertEqual(result, 0)

    def test_constant_value_with_noise(self):
        """Test _get_cutoff with mostly constant value plus small noise"""
        data_sample = np.full((100, 100), 100.0)
        # Add tiny variations
        data_sample += np.random.uniform(-0.01, 0.01, (100, 100))
        no_data_value = -32768
        percentiles = [98]

        result = _get_cutoff(data_sample, no_data_value, percentiles, mask_zeros=False)

        # Should return value close to 100
        self.assertIsInstance(result, float)
        self.assertGreater(result, 90)
        self.assertLess(result, 110)

    def test_bimodal_distribution(self):
        """Test _get_cutoff with bimodal distribution"""
        # Create array with two distinct value clusters
        data_sample = np.zeros((100, 100))
        data_sample[0:50, :] = 20.0
        data_sample[50:100, :] = 80.0
        no_data_value = -32768
        percentiles = [98]

        result = _get_cutoff(data_sample, no_data_value, percentiles, mask_zeros=True)

        # Should compute reasonable cutoff
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0)

    def test_sparse_valid_data(self):
        """Test _get_cutoff with very sparse valid data"""
        data_sample = np.full((100, 100), -32768.0)
        # Only 1% valid data
        valid_indices = np.random.choice(10000, 100, replace=False)
        for idx in valid_indices:
            i, j = divmod(idx, 100)
            data_sample[i, j] = 55.0
        no_data_value = -32768
        percentiles = [98]

        result = _get_cutoff(data_sample, no_data_value, percentiles, mask_zeros=False)

        # Should compute from sparse valid data
        self.assertIsInstance(result, float)
        self.assertGreater(result, 0)


if __name__ == "__main__":
    unittest.main()
