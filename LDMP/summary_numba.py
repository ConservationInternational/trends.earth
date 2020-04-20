import os
import json

import numpy as np


try:
    from numba.pycc import CC
    cc = CC('summary_numba')
except ImportError:
    # Will use these as regular Python functions if numba is not present.
    class CCSubstitute(object):
        # Make a cc.export that doesn't do anything
        def export(*args, **kwargs):
            def wrapper(func):
                return func
            return wrapper
    cc = CCSubstitute()


@cc.export('xtab', '(i2[:,:], i2[:,:], f4[:,:])')
def xtab(x1, x2, areas):
    # x1 values are across rows
    rh = np.unique(x1.ravel())
    # x2 values are across cols
    ch = np.unique(x2.ravel())
    xt = np.zeros((rh.size, ch.size), dtype=np.float32)
    for r in range(x1.shape[0]):
        for c in range(x1.shape[1]):
            r_ind = np.where(rh == x1[r, c])[0]
            c_ind = np.where(ch == x2[r, c])[0]
            if r_ind.size > 0 and c_ind.size > 0:
                xt[r_ind[0], c_ind[0]] += areas[r, c]
    return rh, ch, xt


@cc.export('merge_xtabs', '(i2[:], i2[:], f4[:,:], i2[:], i2[:], f4[:,:])')
def merge_xtabs(tab1_rh, tab1_ch, tab1, tab2_rh, tab2_ch, tab2):
    """Merges two crosstabs - allows for block-by-block crosstabs"""
    # Setup the headers for the combined crosstab
    tab_rh = np.unique(np.concatenate((tab1_rh, tab2_rh)))
    tab_ch = np.unique(np.concatenate((tab1_ch, tab2_ch)))

    # Setup the new table (xt) for the output (possible larger) crosstab 
    xt = np.zeros((tab_rh.size, tab_ch.size), dtype=np.float32)
    for ri in range(xt.shape[0]):
        for ci in range(xt.shape[1]):
            rh_val = tab_rh[ri]
            ch_val = tab_ch[ci]

            # Add in values from xtab1
            tab1_rh_loc = np.where(tab1_rh == rh_val)[0]
            tab1_ch_loc = np.where(tab1_ch == ch_val)[0]
            if tab1_rh_loc.size > 0 and tab1_ch_loc.size > 0:
                xt[ri, ci] += tab1[tab1_rh_loc[0], tab1_ch_loc[0]]

            # Add in values from xtab2
            tab2_rh_loc = np.where(tab2_rh == rh_val)[0]
            tab2_ch_loc = np.where(tab2_ch == ch_val)[0]
            if tab2_rh_loc.size > 0 and tab2_ch_loc.size > 0:
                xt[ri, ci] += tab2[tab2_rh_loc[0], tab2_ch_loc[0]]

    return tab_rh, tab_ch, xt


if __name__ == "__main__":
    cc.compile()
