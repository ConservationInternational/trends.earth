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
            tab1_rh_loc = (tab1_rh == rh_val).nonzero()[0][0]
            tab1_ch_loc = (tab1_ch == ch_val).nonzero()[0][0]
            if np.any(tab1_rh_loc) and np.any(tab1_ch_loc):
                xt[ri, ci] = xt[ri, ci] + tab1[tab1_rh_loc, tab1_ch_loc]
            tab2_rh_loc = (tab2_rh == rh_val).nonzero()[0][0]
            tab2_ch_loc = (tab2_ch == ch_val).nonzero()[0][0]
            if np.any(tab2_rh_loc) and np.any(tab2_ch_loc):
                xt[ri, ci] = xt[ri, ci] + tab2[tab2_rh_loc, tab2_ch_loc]

    return tab_rh, tab_ch, xt

# @cc.export('merge_xtabs', '(i4[:,:], i4[:,:])')
# def merge_xtabs(tab1, tab2):
#     """Merges two crosstabs - allows for block-by-block crosstabs"""
#     headers = np.unique(np.concatenate((tab1[0], tab2[0]), axis=1), axis=1)
#
#     shape_xt = [uniq_vals_col.size for uniq_vals_col in headers]
#     # Make this array flat since it will be used later with ravelled indexing
#     xt = np.zeros(np.prod(shape_xt))
#
#     # This handles combining a crosstab from a new block with an existing one
#     # that has been maintained across blocks
#     def add_xt_block(xt_bl):
#         col_ind = np.tile(tuple(np.where(headers[0] == item) for item in xt_bl[0][0]), xt_bl[0][1].size)
#         row_ind = np.transpose(np.tile(tuple(np.where(headers[1] == item) for item in xt_bl[0][1]), xt_bl[0][0].size))
#         ind = np.ravel_multi_index((col_ind, row_ind), shape_xt)
#         np.add.at(xt, ind.ravel(), xt_bl[1].ravel())
#     add_xt_block(tab1)
#     add_xt_block(tab2)
#
#     return list((headers, xt.reshape(shape_xt)))

if __name__ == "__main__":
    cc.compile()
