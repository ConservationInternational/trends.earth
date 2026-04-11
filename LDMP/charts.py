import hashlib
import json
import math

from osgeo import ogr
from qgis.utils import qgsfunction
from te_algorithms.gdal.land_deg.land_deg_stats import get_stats_for_geom

from .logger import log

_CATEGORIES = [
    ("SDG 15.3.1", "sdg"),
    ("Land Productivity", "land_productivity"),
    ("Land Cover", "land_cover"),
    ("Soil Organic Carbon", "soil_organic_carbon"),
]

_SEGMENTS = [
    ("degraded_pct", "#9b2779", "Degraded"),
    ("stable_pct", "#ffffe0", "Stable"),
    ("improved_pct", "#006500", "Improved"),
    ("nodata_pct", "#000000", "No data"),
]


def _pct(data, category, metric):
    """Extract a percentage value from the stats dict, return int or 0."""
    try:
        cat = data.get(category)
        if not isinstance(cat, dict):
            return 0
        v = cat.get(metric)
        if v is None:
            return 0
        v = float(v)
        if math.isnan(v) or math.isinf(v) or v < 0:
            return 0
        return round(v)
    except Exception:
        return 0


def build_chart_html(stats_json):
    """Render a complete HTML chart from the stats JSON string.

    Returns static HTML with real percentage values baked in.
    """
    data = {}
    if stats_json:
        try:
            data = json.loads(stats_json) if isinstance(stats_json, str) else stats_json
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}

    rows = []
    for label, cat_key in _CATEGORIES:
        cells = []
        for metric, color, _ in _SEGMENTS:
            pct = _pct(data, cat_key, metric)
            border = "border-right:1px solid #ccc;" if color == "#ffffe0" else ""
            cells.append(
                f'<td width="{pct}%" bgcolor="{color}" '
                f'style="{border}" height="20"></td>'
            )
        cells_html = "".join(cells)
        rows.append(
            f"<tr>"
            f'<td width="140" align="right" valign="middle" '
            f'style="padding:3px 8px 3px 0;font-size:11px;">{label}</td>'
            f'<td valign="middle" style="padding:3px 0;">'
            f'<table width="100%" cellspacing="0" cellpadding="0" '
            f'style="border:1px solid #ccc;"><tr>{cells_html}</tr></table>'
            f"</td></tr>"
        )

    legend_items = []
    for _, color, name in _SEGMENTS:
        border = ' style="border:1px solid #ccc;"' if color == "#ffffe0" else ""
        legend_items.append(
            f'<td bgcolor="{color}" width="14" height="14"{border}></td>'
            f'<td style="padding:0 12px 0 4px;font-size:10px;">{name}</td>'
        )

    return (
        '<table width="100%" cellspacing="0" cellpadding="0" '
        'style="font-family:Arial,sans-serif;">'
        '<tr><td colspan="2" style="padding:6px 0;font-size:12px;'
        'font-weight:bold;">Land Degradation Indicators</td></tr>'
        + "".join(rows)
        + '<tr><td colspan="2" style="padding:10px 0 0 0;">'
        '<table cellspacing="0" cellpadding="0"><tr>'
        + "".join(legend_items)
        + "</tr></table></td></tr></table>"
    )


def error_recode_form_open(dialog, layer, feature):
    """Python form init function called when the feature form opens.

    Builds chart HTML from the feature's stats field and injects it into
    the HTML widget.  Injection is deferred by one event-loop tick so that
    all form widgets are fully constructed.
    """
    from qgis.PyQt.QtCore import QTimer

    stats_json = feature["stats"] if feature.fieldNameIndex("stats") >= 0 else None
    html = build_chart_html(stats_json)

    # Defer to next event-loop tick – widgets may not be ready yet.
    QTimer.singleShot(0, lambda: _inject_chart(dialog, html))


def _inject_chart(parent, html):
    """Find the HTML widget in *parent* and set *html* as its content."""
    import sip

    if sip.isdeleted(parent):
        return

    from qgis.PyQt.QtWidgets import QWidget

    # Also search from the top-level window in case the dialog is nested.
    roots = [parent]
    window = parent.window()
    if window is not parent:
        roots.append(window)

    for root in roots:
        # 1. QWebView  (Qt 5 + WebKit builds)
        try:
            from qgis.PyQt.QtWebKitWidgets import QWebView

            for wv in root.findChildren(QWebView):
                wv.setHtml(html)
                return
        except ImportError:
            pass

        # 2. QWebEngineView  (Qt 6 builds)
        try:
            from qgis.PyQt.QtWebEngineWidgets import QWebEngineView

            for wv in root.findChildren(QWebEngineView):
                wv.setHtml(html)
                return
        except ImportError:
            pass

        # 3. QTextBrowser
        from qgis.PyQt.QtWidgets import QTextBrowser

        for tb in root.findChildren(QTextBrowser):
            tb.setHtml(html)
            return

        # 4. QLabel whose text looks like our placeholder
        from qgis.PyQt.QtWidgets import QLabel

        for lbl in root.findChildren(QLabel):
            txt = lbl.text()
            if "Loading chart" in txt or "get_stat_val" in txt:
                lbl.setText(html)
                return

        # 5. Generic – any widget that exposes setHtml()
        for child in root.findChildren(QWidget):
            if hasattr(child, "setHtml") and callable(child.setHtml):
                child.setHtml(html)
                return

    log("_inject_chart: could not find chart widget in form")


def _hash_band(band):
    """Generate a unique hash for a band based on its properties."""
    return hashlib.md5(
        f"{band['name']}_{band['index']}_"
        f"{json.dumps(band.get('metadata', {}), sort_keys=True)}".encode()
    ).hexdigest()


def _sanitize_stats(stats_dict):
    """Replace NaN/Infinity values with 0 so the result is valid JSON."""
    sanitized = {}
    for key, value in stats_dict.items():
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            sanitized[key] = 0.0
        else:
            sanitized[key] = value
    return sanitized


@qgsfunction(args="auto", group="Trends.Earth", usesgeometry=True)
def calculate_error_recode_stats(band_datas, feature, parent, context):
    try:
        band_datas = json.loads(band_datas)
        ogr_geom = ogr.CreateGeometryFromWkt(feature.geometry().asWkt())

        stats = {}
        for band in band_datas:
            # Create bands dictionary with hash key for the new interface
            band_hash = _hash_band(band)
            bands = {
                band_hash: {
                    "name": band["name"],
                    "index": band["index"],
                    "metadata": band.get("metadata", {}),
                }
            }

            band_stats = get_stats_for_geom(
                band["path"], bands, ogr_geom, nodata_value=-32768
            )

            # Extract the single band's stats using the hash key
            stats[band["out_name"]] = _sanitize_stats(band_stats[band_hash])

        return json.dumps(stats)
    except Exception as e:
        log(f"Error calculating error recode stats: {e}")
        return None
