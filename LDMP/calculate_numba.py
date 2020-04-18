import os
import json

import numpy as np


try:
    from numba.pycc import CC
    with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'version.json')) as f:
        version_info = json.load(f)
    cc = CC('calculate_numba_{}'.format(version_info['version'].replace('.', '_')))
    have_numba = True
except ImportError:
    # Will use these as regular Python functions if numba is not present
    have_numba = False
    pass


# Function to conditionally decorate functions with cc.export if numba is 
# present
def cc_decorate(label, signature):
    def decorator(func):
        if not have_numba:
            # Return the function unchanged, not decorated.
            return func
        else:
            # Return the function decorated for numba
            return cc.export(label, signature)
    return decorator


@cc_decorate('ldn_recode_traj', 'i2[:,:](i2[:,:])')
def ldn_recode_traj(x):
    # Recode trajectory into deg, stable, imp. Capture trends that are at least 
    # 95% significant.
    #
    # Remember that traj is coded as:
    # -3: 99% signif decline
    # -2: 95% signif decline
    # -1: 90% signif decline
    #  0: stable
    #  1: 90% signif increase
    #  2: 95% signif increase
    #  3: 99% signif increase
    shp = x.shape
    x = x.ravel()
    x[(x >= -1) & (x <= 1)] = 0
    x[(x >= -3) & (x < -1)] = -1
    # -1 and 1 are not signif at 95%, so stable
    x[(x > 1) & (x <= 3)] = 1
    return(np.reshape(x, shp))


@cc_decorate('ldn_recode_state', 'i2[:,:](i2[:,:])')
def ldn_recode_state(x):
    # Recode state into deg, stable, imp. Note the >= -10 is so no data 
    # isn't coded as degradation. More than two changes in class is defined 
    # as degradation in state.
    shp = x.shape
    x = x.ravel()
    x[(x > -2) & (x < 2)] = 0
    x[(x >= -10) & (x <= -2)] = -1
    x[x >= 2] = 1
    return(np.reshape(x, shp))


@cc_decorate('ldn_make_prod5', 'i2[:,:](i2[:,:], i2[:,:], i2[:,:] ,i2[:,:])')
def ldn_make_prod5(traj, state, perf, mask):
    # Coding of LPD (prod5)
    # 1: declining
    # 2: early signs of decline
    # 3: stable but stressed
    # 4: stable
    # 5: improving
    # -32768: no data
    # Declining = 1
    shp = traj.shape

    traj = traj.ravel()
    state = state.ravel()
    perf = perf.ravel()
    mask = mask.ravel()

    x = traj.copy()

    x[traj == -1] = 1
    # Stable = 4
    x[traj == 0] = 4
    # Improving = 5
    x[traj == 1] = 5

    # Stable due to agreement in perf and state but positive trajectory
    x[(traj == 1) & (state == -1) & (perf == -1)] = 4
    # Stable but stressed
    x[(traj == 0) & (state == 0) & (perf == -1)] = 3
    # Early signs of decline
    x[(traj == 0) & (state == -1) & (perf == 0)] = 2

    # Ensure NAs carry over to productivity indicator layer
    x[(traj == -32768) | (perf == -32768) | (state == -32768)] = -32768

    # Ensure masked areas carry over to productivity indicator
    x[mask == -32767] = -32767

    return(np.reshape(x, shp))


@cc_decorate('ldn_total_by_trans', '(f4[:,:], i2[:,:], f4[:,:])')
def ldn_total_by_trans(d, trans_a, cell_areas):
    """Calculates a total table for an array"""
    d = d.ravel()
    trans_a = trans_a.ravel()
    trans = np.unique(trans_a)
    cell_areas = cell_areas.ravel()
    # Values less than zero are missing data flags
    d[d < 0] = 0
    totals = np.zeros(trans.size, dtype=np.float32)
    for i in range(trans.size):
        # Only sum values for this_trans, and where soc has a valid value
        # (negative values are missing data flags)
        vals = d[trans_a == trans[i]] * cell_areas[trans_a == trans[i]]
        totals[i] += np.sum(vals)
    return trans, totals

# @cc_decorate('ldn_total_by_trans_merge', '(f4[:], i2[:], f4[:], i2[:])')
# def ldn_total_by_trans_merge(total1, trans1, total2, trans2):
#     """Calculates a total table for an array"""
#     # Combine past totals with these totals
#     trans = np.unique(np.concatenate((trans1, trans2)))
#     totals = np.zeros(trans.size, dtype=np.float32)
#     for i in range(trans.size):
#         trans1_loc = np.where(trans1 == trans[i])[0]
#         trans2_loc = np.where(trans2 == trans[i])[0]
#         if trans1_loc.size > 0:
#             totals[i] = totals[i] + total1[trans1_loc[0]]
#         if trans2_loc.size > 0:
#             totals[i] = totals[i] + total2[trans2_loc[0]]
#     return trans, totals


@cc_decorate('ldn_total_deg', 'f4[4](i2[:,:], b1[:,:], f4[:,:])')
def ldn_total_deg(x, water, cell_areas):
    """Calculates a total table for an array"""
    x = x.ravel()
    cell_areas = cell_areas.ravel()
    x[water.ravel()] = -32767
    out = np.zeros((4), dtype=np.float32)
    out[0] = np.sum(cell_areas[x == 1])
    out[1] = np.sum(cell_areas[x == 0])
    out[2] = np.sum(cell_areas[x == -1])
    out[3] = np.sum(cell_areas[x == -32768])
    return out


if __name__ == "__main__":
    cc.compile()
