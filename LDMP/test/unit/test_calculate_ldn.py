# -*- coding: utf-8 -*-
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

import os
import sys

import numpy as np

from qgis.testing import unittest

from LDMP.calculate_ldn import ldn_total_by_trans_merge

from LDMP.test import add_default_bands_to_map

from LDMP.calculate import (ldn_make_prod5, ldn_recode_state,
    ldn_recode_traj, ldn_total_by_trans, ldn_total_deg_f)


class recode_stateTests(unittest.TestCase):
    def recode_to_deg(self):
        out = recode_state(np.array((-10, -2), dtype=np.int16))
        self.assertEquals(out, np.array((-1, 1), dtype=np.int16))

    def recode_to_stable(self):
        out = recode_state(np.array((-1, 1), dtype=np.int16))
        self.assertEquals(out, np.array((0, 0), dtype=np.int16))

    def recode_to_improve(self):
        out = recode_state(np.array((2, 10), dtype=np.int16))
        self.assertEquals(out, np.array((1, 1), dtype=np.int16))


class ldn_total_by_transTests(unittest.TestCase):
    def test_trans(self):
        trans, totals = ldn_total_by_trans(np.asarray([[1, 2, 3, 4, 5]], dtype=np.float32),
                                           np.asarray([[101, 102, 103, 104, 105]], dtype=np.int16),
                                           np.asarray([[11, 12, 13, 14, 15]], dtype=np.float32))
        self.assertTrue(all(trans == np.asarray((101, 102, 103, 104, 105), dtype=np.int16)))

    def test_trans_repeated_trans(self):
        trans, totals = ldn_total_by_trans(np.asarray([[1, 2, 3, 4, 5, 1]], dtype=np.float32),
                                           np.asarray([[101, 102, 103, 104, 105, 101]], dtype=np.int16),
                                           np.asarray([[11, 12, 13, 14, 15, 11]], dtype=np.float32))
        self.assertTrue(all(trans == np.asarray((101, 102, 103, 104, 105), dtype=np.int16)))
        self.assertTrue(all(totals == np.asarray((22, 24, 39, 56, 75), dtype=np.float32)))

    def test_totals(self):
        trans, totals = ldn_total_by_trans(np.asarray([[1, 2, 3, 4, 5]], dtype=np.float32),
                                           np.asarray([[101, 102, 103, 104, 105]], dtype=np.int16),
                                           np.asarray([[11, 12, 13, 14, 15]], dtype=np.float32))
        self.assertTrue(all(totals == np.asarray((11, 24, 39, 56, 75), dtype=np.float32)))

class ldn_total_by_trans_mergeTests(unittest.TestCase):
    def test_merge_trans_same(self):
        trans1, totals1 = ldn_total_by_trans(np.asarray([[1, 2, 3, 4, 5]], dtype=np.float32),
                                             np.asarray([[101, 102, 103, 104, 105]], dtype=np.int16),
                                             np.asarray([[11, 12, 13, 14, 15]], dtype=np.float32))
        trans2, totals2 = ldn_total_by_trans(np.asarray([[1, 2, 3, 4, 5]], dtype=np.float32),
                                             np.asarray([[101, 102, 103, 104, 105]], dtype=np.int16),
                                             2*np.asarray([[11, 12, 13, 14, 15]], dtype=np.float32))
        trans, totals = ldn_total_by_trans_merge(totals1, trans1, totals2, trans2)
        self.assertTrue(all(trans == np.asarray((101, 102, 103, 104, 105), dtype=np.int16)))
        self.assertTrue(all(totals == np.asarray((33, 72, 117, 168, 225), dtype=np.float32)))

    def test_merge_trans_different(self):
        trans1, totals1 = ldn_total_by_trans(np.asarray([[1, 2, 3, 4, 5]], dtype=np.float32),
                                             np.asarray([[101, 102, 103, 104, 105]], dtype=np.int16),
                                             np.asarray([[11, 12, 13, 14, 15]], dtype=np.float32))
        trans2, totals2 = ldn_total_by_trans(np.asarray([[1, 2, 3, 4, 5]], dtype=np.float32),
                                             2*np.asarray([[101, 102, 103, 104, 105]], dtype=np.int16),
                                             2*np.asarray([[11, 12, 13, 14, 15]], dtype=np.float32))
        trans, totals = ldn_total_by_trans_merge(totals1, trans1, totals2, trans2)
        self.assertTrue(all(trans == np.asarray((101, 102, 103, 104, 105, 202, 204, 206, 208, 210), dtype=np.int16)))
        self.assertTrue(all(totals == np.asarray((11, 24, 39, 56, 75, 22, 48, 78, 112, 150), dtype=np.float32)))


class ldn_total_deg_fTests(unittest.TestCase):
    def test_zero_array(self):
        total = ldn_total_deg_f(np.zeros((10, 10), dtype=np.int16), np.zeros((10, 10), dtype=np.bool), np.zeros((10, 10), dtype=np.float32))
        self.assertEquals(np.shape(total), (4,))
        self.assertEquals(np.sum(total), 0.0)


def CalculateLDNUnitSuite():
    suite = unittest.TestSuite()
    suite.addTests(unittest.makeSuite(recode_stateTests, 'test'))
    suite.addTests(unittest.makeSuite(ldn_total_deg_fTests, 'test'))
    suite.addTests(unittest.makeSuite(ldn_total_by_transTests, 'test'))
    suite.addTests(unittest.makeSuite(ldn_total_by_trans_mergeTests, 'test'))
    return suite


def run_all():
    _suite = unittest.TestSuite()
    _suite.addTest(CalculateLDNUnitSuite())
    unittest.TextTestRunner(verbosity=3, stream=sys.stdout).run(_suite)
