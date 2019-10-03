import numpy as np

from numba.pycc import CC

cc = CC('summary_numba')
#
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
