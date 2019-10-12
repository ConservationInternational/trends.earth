import numpy as np

from numba.pycc import CC

cc = CC('summary_numba')


@cc.export('merge_xtabs', '(i4[:], i4[:], f8[:,:], i4[:], i4[:], f8[:,:])')
def merge_xtabs(tab1_rh, tab1_ch, tab1, tab2_rh, tab2_ch, tab2):
    """Merges two crosstabs - allows for block-by-block crosstabs"""
    tab_rh = np.unique(np.concatenate((tab1_rh, tab2_rh)))
    tab_ch = np.unique(np.concatenate((tab1_ch, tab2_ch)))
    shape_xt = (tab_rh.size, tab_ch.size)

    # Make this array flat since it will be used later with ravelled indexing
    xt = np.zeros(shape_xt, dtype=np.float64)

    for ri in range(0, shape_xt[0]):
        for ci in range(0, shape_xt[1]):
            rh_val = tab_rh[ri]
            ch_val = tab_ch[ci]
            tab1_rh_loc = np.where(tab1_rh == rh_val)[0][0]
            tab1_ch_loc = np.where(tab1_ch == ch_val)[0][0]
            xt[ri, ci] = xt[ri, ci] + tab1[tab1_rh_loc, tab1_ch_loc]
            tab2_rh_loc = np.where(tab2_rh == rh_val)[0][0]
            tab2_ch_loc = np.where(tab2_ch == ch_val)[0][0]
            xt[ri, ci] = xt[ri, ci] + tab2[tab2_rh_loc, tab2_ch_loc]

    return tab_rh, tab_ch, xt


if __name__ == "__main__":
    cc.compile()
