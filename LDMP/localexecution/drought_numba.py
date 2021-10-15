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


@numba.jit(nopython=True)
@cc.export('drought_class', 'i2[:,:](i2[:,:])')
def drought_class(spi):
    # 0 - -1: mild drought (code as 1)
    # -1 - -1.5: moderate drought (code as 2)
    # -1.5 - -2: severe drought (code as 3)
    # -2 - inf: extreme drought (code as 4)

    shp = spi.shape
    spi = spi.ravel()
    out = spi.copy()

    out[spi > 0] = 0
    out[(spi < 0) & (spi >= -1000)] = 1
    out[(spi < -1000) & (spi >= -1500)] = 2
    out[(spi < -1500) & (spi >= -2000)] = 3
    out[(spi < -2000) & (spi >= -30000)] = 4

    out[spi == NODATA_VALUE] = NODATA_VALUE

    return np.reshape(out, shp)


@numba.jit(nopython=True)
@cc.export(
    'jrc_sum_and_count',
    'UniTuple(i2, i2)(f8[:,:], i2[:,:])'
)
def jrc_sum_and_count(jrc, mask):
    jrc = jrc.ravel()
    out = jrc.copy()

    out[mask == MASK_VALUE] = NODATA_VALUE
    out = jrc.masked_equal(NODATA_VALUE)

    return (out.sum(), out.count())


# Below not currently used, but saving for future use
@numba.jit(nopython=True)
@cc.export('drought_class', 'i2[:,:](i2[:,:])')
def jrc_class(jrc):
    # 0 - -1: mild drought (code as 1)
    # -1 - -1.5: moderate drought (code as 2)
    # -1.5 - -2: severe drought (code as 3)
    # -2 - inf: extreme drought (code as 4)
    
    shp = jrc.shape
    jrc = jrc.ravel()
    out = jrc.copy()

    out[jrc > 0] = 0
    out[(jrc >= 0) & (jrc < 3930)] = 1
    out[(jrc >= 3930) & (jrc < 4718)] = 2
    out[(jrc >= 4718) & (jrc < 9270)] = 3
    out[(jrc >= 9270) & (jrc < 1)] = 4

    out[jrc == NODATA_VALUE] = NODATA_VALUE

    return np.reshape(out, shp)
