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
@cc.export('recode_traj', 'i2[:,:](i2[:,:])')
def recode_traj(x):
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
    x = x.copy().ravel()
    # -1 and 1 are not signif at 95%, so stable
    x[(x >= -1) & (x <= 1)] = 0
    x[(x >= -3) & (x < -1)] = -1
    x[(x > 1) & (x <= 3)] = 1
    return np.reshape(x, shp)


@numba.jit(nopython=True)
@cc.export('recode_state', 'i2[:,:](i2[:,:])')
def recode_state(x):
    # Recode state into deg, stable, imp. Note the >= -10 is so no data 
    # isn't coded as degradation. More than two changes in class is defined 
    # as degradation in state.
    shp = x.shape
    x = x.copy().ravel()
    x[(x > -2) & (x < 2)] = 0
    x[(x >= -10) & (x <= -2)] = -1
    x[x >= 2] = 1
    return np.reshape(x, shp)


@numba.jit(nopython=True)
@cc.export('calc_progress_lc_deg', 'i2[:,:](i2[:,:], i2[:,:])')
def calc_progress_lc_deg(initial, final):
    # First need to calculate transitions, then recode them as deg, stable, 
    # improved
    #
    # -32768: no data
    shp = initial.shape
    initial = initial.ravel()
    final = final.ravel()
    out = initial.copy()

    # improvements on areas that were degraded at baseline -> stable
    out[(initial == -1) & (final == 1)] = 0
    # improvements on areas that were stable at baseline -> improved
    out[(initial == 0) & (final == 1)] = 1
    # degradation during progress -> degraded
    out[final == -1] = -1

    return np.reshape(out, shp)


@numba.jit(nopython=True)
@cc.export('calc_prod5', 'i2[:,:](i2[:,:], i2[:,:], i2[:,:])')
def calc_prod5(traj, state, perf):
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

    x = traj.copy()

    x[traj == -1] = 1
    # Stable = 4
    x[traj == 0] = 4
    # Improving = 5
    x[traj == 1] = 5

    # Stressed
    x[(traj == 0) & (state == 0) & (perf == -1)] = 3
    # Agreement in perf and state but positive trajectory is considered 
    # moderate decline
    x[(traj == 1) & (state == -1) & (perf == -1)] = 2
    # Moderate decline if state neg but traj and perf stable
    x[(traj == 0) & (state == -1) & (perf == 0)] = 2
    # Agreement in perf and state and stable trajectory is considered degrading
    x[(traj == 0) & (state == -1) & (perf == -1)] = 1

    # Ensure NAs carry over to productivity indicator layer
    x[(traj == NODATA_VALUE) |
      (perf == NODATA_VALUE) |
      (state == NODATA_VALUE)] = NODATA_VALUE

    return np.reshape(x, shp)


@numba.jit(nopython=True)
@cc.export('prod5_to_prod3', 'i2[:,:](i2[:,:])')
def prod5_to_prod3(prod5):
    shp = prod5.shape
    prod5 = prod5.ravel()
    out = prod5.copy()
    out[(prod5 == 1) & (prod5 == 2)] = -1
    out[(prod5 == 3) & (prod5 == 4)] = 0
    out[prod5 == 5] = 1
    return np.reshape(out, shp)


@numba.jit(nopython=True)
@cc.export('calc_lc_trans', 'i4[:,:](i2[:,:], i2[:,:], i4)')
def calc_lc_trans(lc_bl, lc_tg, multiplier):
    shp = lc_bl.shape
    lc_bl = lc_bl.ravel()
    lc_tg = lc_tg.ravel()
    a_trans_bl_tg = lc_bl * multiplier + lc_tg
    a_trans_bl_tg[np.logical_or(lc_bl < 1, lc_tg < 1)] = NODATA_VALUE
    return np.reshape(a_trans_bl_tg, shp)


@numba.jit(nopython=True)
@cc.export('recode_deg_soc', 'i2[:,:](i2[:,:], i2[:,:])')
def recode_deg_soc(soc, water):
    '''recode SOC change layer from percent change into a categorical map'''
    # Degradation in terms of SOC is defined as a decline of more
    # than 10% (and improving increase greater than 10%)
    shp = soc.shape
    soc = soc.ravel()
    water = water.ravel()
    out = soc.copy()
    out[(soc >= -101) & (soc <= -10)] = -1
    out[(soc > -10) & (soc < 10)] = 0
    out[soc >= 10] = 1
    out[water] = NODATA_VALUE  # don't count soc in water
    return np.reshape(out, shp)


@numba.jit(nopython=True)
@cc.export('calc_soc_pch', 'i2[:,:](i2[:,:], i2[:,:])')
def calc_soc_pch(soc_bl, soc_tg):
    '''calculate percent change in SOC from initial and final SOC'''
    # Degradation in terms of SOC is defined as a decline of more
    # than 10% (and improving increase greater than 10%)
    shp = soc_bl.shape
    soc_bl = soc_bl.ravel()
    soc_tg = soc_tg.ravel()
    out = np.zeros(soc_bl.shape, dtype=np.int16)
    soc_chg = (soc_tg.astype(np.float64) / soc_bl.astype(np.float64)) * 100.
    soc_chg[(soc_bl == NODATA_VALUE) | (soc_tg == NODATA_VALUE)] = NODATA_VALUE
    return np.reshape(out, shp)


@numba.jit(nopython=True)
@cc.export('calc_deg_soc', 'i2[:,:](i2[:,:], i2[:,:], i2[:,:])')
def calc_deg_soc(soc_bl, soc_tg, water):
    '''calculate SOC degradation from initial and final SOC'''
    # Degradation in terms of SOC is defined as a decline of more
    # than 10% (and improving increase greater than 10%)
    shp = soc_bl.shape
    soc_bl = soc_bl.ravel()
    soc_tg = soc_tg.ravel()
    water = water.ravel()
    out = np.zeros(soc_bl.shape, dtype=np.int16)
    soc_chg = (soc_tg.astype(np.float64) / soc_bl.astype(np.float64)) * 100.
    soc_chg[(soc_bl == NODATA_VALUE) | (soc_tg == NODATA_VALUE)] = NODATA_VALUE
    out[(soc_chg >= -101.) & (soc_chg <= -10.)] = -1
    out[(soc_chg > -10.) & (soc_chg < 10.)] = 0
    out[soc_chg >= 10.] = 1
    out[water] = NODATA_VALUE  # don't count soc in water
    return np.reshape(out, shp)


@numba.jit(nopython=True)
@cc.export('calc_deg_lc', 'i2[:,:](i2[:,:], i2[:,:], i2[:], i2[:], i4)')
def calc_deg_lc(lc_bl, lc_tg, trans_code, trans_meaning, multiplier):
    '''calculate land cover degradation'''
    shp = lc_bl.shape
    trans = calc_lc_trans(lc_bl, lc_tg, multiplier)
    trans = trans.ravel()
    lc_bl = lc_bl.ravel()
    lc_tg = lc_tg.ravel()
    out = np.zeros(lc_bl.shape, dtype=np.int16)
    for code, meaning in zip(trans_code, trans_meaning):
        out[trans == code] = meaning
    out[
        np.logical_or(lc_bl == NODATA_VALUE, lc_tg == NODATA_VALUE)
    ] = NODATA_VALUE
    return np.reshape(out, shp)


@numba.jit(nopython=True)
@cc.export('calc_deg_sdg', 'i2[:,:](i2[:,:], i2[:,:], i2[:,:])')
def calc_deg_sdg(deg_prod3, deg_lc, deg_soc):
    shp = deg_prod3.shape
    deg_prod3 = deg_prod3.ravel()
    deg_lc = deg_lc.ravel()
    deg_soc = deg_soc.ravel()
    out = deg_prod3.copy()

    # Degradation by either lc or soc (or prod3)
    out[(deg_lc == -1) | (deg_soc == -1)] = -1

    # Improvements by lc or soc, but only if one of the other
    # three indicators doesn't indicate a decline
    out[(out == 0) & ((deg_lc == 1) | (deg_soc == 1))] = 1

    # nodata masking was already done for prod3, but need to do it again in
    # case values from another layer overwrote those missing value
    # indicators. -32678 is missing
    out[(deg_prod3 == NODATA_VALUE) |
        (deg_lc == NODATA_VALUE) |
        (deg_soc == NODATA_VALUE)] = NODATA_VALUE

    return np.reshape(out, shp)
