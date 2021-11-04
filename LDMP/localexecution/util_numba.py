import numpy as np


try:
    import numba
    from numba.pycc import CC
    cc = CC('ldn_numba')
except ImportError:
    # Will use these as regular Python functions if numba is not present.
    class DecoratorSubstitute(object):
        # Make a cc.export that doesn't do anything
        def export(*args, **kwargs):
            def wrapper(func):
                return func
            return wrapper

        # Make a numba.jit that doesn't do anything
        def jit(*args, **kwargs):
            def wrapper(func):
                return func
            return wrapper
    cc = DecoratorSubstitute()
    numba = DecoratorSubstitute()


# Ensure mask and nodata values are saved as 16 bit integers to keep numba 
# happy
NODATA_VALUE = np.array([-32768], dtype=np.int16)
MASK_VALUE = np.array([-32767], dtype=np.int16)

# Calculate the area of a slice of the globe from the equator to the parallel
# at latitude f (on WGS84 ellipsoid). Based on:
# https://gis.stackexchange.com/questions/127165/more-accurate-way-to-calculate-area-of-rasters
@numba.jit(nopython=True)
@cc.export('slice_area', 'f8(f8)')
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
@numba.jit(nopython=True)
@cc.export('calc_cell_area', 'f8(f8, f8, f8)')
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


@numba.jit(nopython=True)
@cc.export('zonal_total', 'DictType(i2, f8)(i2[:,:], f8[:,:], b1[:,:])')
def zonal_total(z, d, mask):
    z = z.copy().ravel()
    d = d.ravel()
    mask = mask.ravel()
    # Carry over nodata values from data layer to z so that they aren't
    # included in the totals
    z[d == NODATA_VALUE] = NODATA_VALUE
    z[mask] = MASK_VALUE
    #totals = numba.typed.Dict.empty(numba.types.int16, numba.types.float64)
    totals = dict()
    for i in range(z.shape[0]):
        if z[i] not in totals:
            totals[z[i]] = d[i]
        else:
            totals[z[i]] += d[i]
    return totals


@numba.jit(nopython=True, boundscheck=True)
@cc.export('zonal_total_weighted', 'DictType(i2, f8)(i2[:,:], i2[:,:], f8[:,:], b1[:,:])')
def zonal_total_weighted(z, d, weights, mask):
    z = z.copy().ravel()
    d = d.ravel()
    weights = weights.ravel()
    mask = mask.ravel()
    # Carry over nodata values from data layer to z so that they aren't
    # included in the totals
    z[d == NODATA_VALUE] = NODATA_VALUE
    z[mask] = MASK_VALUE
    #totals = numba.typed.Dict.empty(numba.types.int16, numba.types.float64)
    totals = dict()
    for i in range(z.shape[0]):
        if z[i] not in totals:
            totals[z[i]] = d[i] * weights[i]
        else:
            totals[z[i]] += d[i] * weights[i]
    return totals


@numba.jit(nopython=True)
@cc.export('bizonal_total', 'DictType(UniTuple(i2, 2), f8)(i2[:,:], i2[:,:], f8[:,:], b1[:,:])')
def bizonal_total(z1, z2, d, mask):
    z1 = z1.copy().ravel()
    z2 = z2.copy().ravel()
    d = d.ravel()
    mask = mask.ravel()
    # Carry over nodata values from data layer to z so that they aren't
    # included in the totals
    z1[d == NODATA_VALUE] = NODATA_VALUE
    z1[mask] = MASK_VALUE
    # Carry over nodata values from data layer to z so that they aren't
    # included in the totals
    z2[d == NODATA_VALUE] = NODATA_VALUE
    z2[mask] = MASK_VALUE
    #tab = numba.typed.Dict.empty(numba.types.int64, numba.types.float64)
    tab = dict()
    for i in range(z1.shape[0]):
        key = (z1[i], z2[i])
        if key not in tab:
            tab[key] = d[i]
        else:
            tab[key] += d[i]
    return tab


@numba.jit(nopython=True)
def accumulate_dicts(z):
    out = z[0]
    for d in z[1:]:
        _combine_dicts(out, d)
    return out


@numba.jit(nopython=True)
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
