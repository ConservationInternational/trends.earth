import os
import json

import numpy as np


try:
    from numba.pycc import CC
    cc = CC('ldn_numba')
except ImportError:
    # Will use these as regular Python functions if numba is not present.
    class CCSubstitute(object):
        # Make a cc.export that doesn't do anything
        def export(*args, **kwargs):
            def wrapper(func):
                return func
            return wrapper
    cc = CCSubstitute()


from numba import jit


# Calculate the area of a slice of the globe from the equator to the parallel
# at latitude f (on WGS84 ellipsoid). Based on:
# https://gis.stackexchange.com/questions/127165/more-accurate-way-to-calculate-area-of-rasters
#@cc.export('slice_area', 'f8(f8)')
@jit(nopython=True)
def slice_area(f):
    a = 6378137.  # in meters
    b = 6356752.3142  # in meters,
    e = np.sqrt(1 - pow(b / a, 2))
    zp = 1 + e * np.sin(f)
    zm = 1 - e * np.sin(f)
    return (np.pi * pow(b, 2) * ((2 * np.arctanh(e * np.sin(f))) /
            (2 * e) + np.sin(f) / (zp * zm)))


# Formula to calculate area of a raster cell on WGS84 ellipsoid, following
# https://gis.stackexchange.com/questions/127165/more-accurate-way-to-calculate-area-of-rasters
#@cc.export('calc_cell_area', 'f8(f8, f8, f8)')
@jit(nopython=True)
def calc_cell_area(ymin, ymax, x_width):
    if (ymin > ymax):
        temp = 0
        temp = ymax
        ymax = ymin
        ymin = temp
    # ymin: minimum latitude
    # ymax: maximum latitude
    # x_width: width of cell in degrees
    return ((slice_area(np.deg2rad(ymax)) - slice_area(np.deg2rad(ymin)))
            * (x_width / 360.))


#@cc.export('ldn_recode_traj', 'i2[:,:](i2[:,:])')
@jit(nopython=True)
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


#@cc.export('ldn_recode_state', 'i2[:,:](i2[:,:])')
@jit(nopython=True)
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


#@cc.export('ldn_make_prod5', 'i2[:,:](i2[:,:], i2[:,:], i2[:,:] ,i2[:,:])')
@jit(nopython=True)
def calc_prod5(traj, state, perf, mask):
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


@jit(nopython=True)
def prod5_to_prod3(prod5):
    shp = prod5.shape
    prod5 = prod5.ravel()
    out = prod5.copy()
    out[(prod5 >= 1) & (prod5 <= 3)] = -1
    out[prod5 == 4] = 0
    out[prod5 == 5] = 1
    return(np.reshape(out, shp))


@jit(nopython=True)
def calc_deg_soc(soc, water, mask):
    '''recode SOC change layer from percent change into a categorical map'''
    # Degradation in terms of SOC is defined as a decline of more
    # than 10% (and improving increase greater than 10%)
    shp = soc.shape
    soc = soc.ravel()
    water = water.ravel()
    mask = mask.ravel()
    out = soc.copy()
    out[(soc >= -101) & (soc <= -10)] = -1
    out[(soc > -10) & (soc < 10)] = 0
    out[soc >= 10] = 1
    out[water] = -32768  # don't count soc in water
    out[mask] = -32767
    return(np.reshape(out, shp))


@jit(nopython=True)
def calc_deg_sdg(deg_prod3, deg_lc, deg_soc, mask):
    shp = deg_prod3.shape
    deg_prod3 = deg_prod3.ravel()
    deg_lc = deg_lc.ravel()
    deg_soc = deg_soc.ravel()
    mask = mask.ravel()
    out = deg_prod3.copy()

    # Degradation by either lc or soc (or prod3)
    out[(deg_lc == -1) | (deg_soc == -1)] = -1

    # Improvements by lc or soc, but only if one of the other
    # three indicators doesn't indicate a decline
    out[(out == 0) & ((deg_lc == 1) | (deg_soc == 1))] = 1

    # Note masking was already done for prod3, but need to do it again in
    # case values from another layer overwrote those missing value
    # indicators. -32678 is missing, -32767 is mask
    out[(deg_prod3 == -32768) | (deg_lc == -32768) | (deg_soc == -32768)] = -32768
    out[mask] = -32767

    return(np.reshape(out, shp))


@jit(nopython=True)
def zonal_total(z, d, mask):
    z = z.ravel()
    d = d.ravel()
    mask = mask.ravel()
    z[mask] = -32767
    totals = dict()
    for i in range(z.shape[0]):
        if z[i] not in totals:
            totals[z[i]] = d[i]
        else:
            totals[z[i]] += d[i]
    return totals


@jit(nopython=True)
def bizonal_total(z1, z2, d, mask):
    z1 = z1.ravel()
    z2 = z2.ravel()
    d = d.ravel()
    mask = mask.ravel()
    z1[mask] = -32767
    z2[mask] = -32767
    tab = dict()
    for i in range(z1.shape[0]):
        if (z1[i], z2[i]) not in tab:
            tab[(z1[i], z2[i])] = d[i]
        else:
            tab[(z1[i], z2[i])] += d[i]
    return tab


def accumulate_dicts(z):
    out = z[0]
    for d in z[1:]:
        _combine_dicts(out, d)
    return out


@jit(nopython=True)
def _combine_dicts(z1, z2):
    out = z1
    for key in z2:
        if key in out:
            out[key] += z2[key]
        else:
            out[key] = z2[key]
    return out


if __name__ == "__main__":
    cc.compile()
