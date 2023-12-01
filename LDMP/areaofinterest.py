import functools
import json
import traceback
import typing
from pathlib import Path

import qgis.core
import qgis.gui
from osgeo import gdal
from osgeo import ogr
from qgis.core import Qgis
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QCoreApplication
from qgis.utils import iface as qgisiface

from . import conf
from . import download
from .layers import _get_qgis_version
from .logger import log


class tr_areaofinterest:
    def tr(message):
        return QCoreApplication.translate("tr_areaofinterest", message)


def get_city_geojson() -> typing.Dict:
    current_country = conf.settings_manager.get_value(conf.Setting.COUNTRY_NAME)
    country_code = conf.ADMIN_BOUNDS_KEY[current_country].code
    current_city = conf.settings_manager.get_value(conf.Setting.CITY_NAME)
    current_country_cities = conf.settings_manager.get_value(conf.Setting.CITY_KEY)
    wof_id = current_country_cities[current_city]
    return conf.CITIES[country_code][str(wof_id)].geojson


def get_admin_poly_geojson():
    current_country = conf.settings_manager.get_value(conf.Setting.COUNTRY_NAME)
    country_code = conf.ADMIN_BOUNDS_KEY[current_country].code
    admin_polys_filename = f"admin_bounds_polys_{country_code}.json.gz"
    admin_polys = download.read_json(admin_polys_filename, verify=False)
    if not admin_polys:
        return None
    current_region = conf.settings_manager.get_value(conf.Setting.REGION_NAME)
    if (not current_region) or (current_region == "All regions"):
        result = admin_polys["geojson"]
    else:
        region_code = conf.ADMIN_BOUNDS_KEY[current_country].level1_regions[
            current_region
        ]
        result = admin_polys["admin1"][region_code]["geojson"]
    return result


def validate_country_region() -> typing.Tuple[typing.Optional[typing.Dict], str]:
    error_msg = ""
    country_name = conf.settings_manager.get_value(conf.Setting.COUNTRY_NAME)
    if not country_name:
        geojson = None
        error_msg = "Choose a first level administrative boundary."

    geojson = get_admin_poly_geojson()
    if not geojson:
        geojson = None
        error_msg = "Unable to load administrative boundaries."
    return geojson, error_msg


def validate_vector_path() -> typing.Tuple[Path, str]:
    error_msg = ""
    try:
        vector_path = Path(
            conf.settings_manager.get_value(conf.Setting.VECTOR_FILE_PATH)
        )
    except TypeError:
        vector_path = None
        error_msg = "Choose a file to define the area of interest."
    else:
        if not vector_path.is_file():
            error_msg = f"File {vector_path!r} cannot be accessed"
    return vector_path, error_msg


class AOI:
    def __init__(self, crs_dst):
        self.crs_dst = crs_dst

    def get_crs_dst_wkt(self):
        return self.crs_dst.toWkt()

    def update_from_file(self, f, wrap=False):
        log('Setting up AOI from file at {}"'.format(f))
        l = qgis.core.QgsVectorLayer(f, "calculation boundary", "ogr")
        if not l.isValid():
            raise RuntimeError(
                f"Unable to load area of interest from {f}. There may be a problem "
                f"with the file or coordinate system. Try manually loading this file "
                f"into QGIS to verify that it displays properly. If you continue to "
                f"have problems with this file, send us a message at "
                f"trends.earth@conservation.org."
            )
        if (
            l.wkbType() == qgis.core.QgsWkbTypes.Polygon
            or l.wkbType() == qgis.core.QgsWkbTypes.PolygonZ
            or l.wkbType() == qgis.core.QgsWkbTypes.MultiPolygon
            or l.wkbType() == qgis.core.QgsWkbTypes.MultiPolygonZ
        ):
            self.datatype = "polygon"
        elif (
            l.wkbType() == qgis.core.QgsWkbTypes.Point
            or l.wkbType() == qgis.core.QgsWkbTypes.PointZ
            or l.wkbType() == qgis.core.QgsWkbTypes.MultiPoint
            or l.wkbType() == qgis.core.QgsWkbTypes.MultiPointZ
        ):
            self.datatype = "point"
        else:
            raise RuntimeError(
                f"Failed to process area of interest - unknown geometry "
                f"type: {l.wkbType()}"
            )
        self.l = _transform_layer(l, self.crs_dst, datatype=self.datatype, wrap=wrap)

    def update_from_geojson(
        self, geojson, crs_src="epsg:4326", datatype="polygon", wrap=False
    ):
        log("Setting up AOI with geojson. Wrap is {}.".format(wrap))
        self.datatype = datatype
        # Note geojson is assumed to be in 4326
        l = qgis.core.QgsVectorLayer(
            "{datatype}?crs={crs}".format(datatype=self.datatype, crs=crs_src),
            "calculation boundary",
            "memory",
        )
        ds = ogr.Open(json.dumps(geojson))
        layer_in = ds.GetLayer()
        feats_out = []
        for i in range(0, layer_in.GetFeatureCount()):
            feat_in = layer_in.GetFeature(i)
            feat = qgis.core.QgsFeature(l.fields())
            geom = qgis.core.QgsGeometry()
            geom.fromWkb(feat_in.geometry().ExportToWkb())
            feat.setGeometry(geom)
            feats_out.append(feat)
        l.dataProvider().addFeatures(feats_out)
        l.commitChanges()
        if not l.isValid():
            raise RuntimeError("Failed to add geojson to temporary layer.")
        self.l = _transform_layer(l, self.crs_dst, datatype=self.datatype, wrap=wrap)

    def get_unary_geometry(self):
        "Calculate a single feature that is the union of all the features in layer"

        geometries = []
        n = 1
        for f in self.get_layer_wgs84().getFeatures():
            # Get an OGR geometry from the QGIS geometry
            geom = f.geometry()
            if not geom.isGeosValid():
                raise RuntimeError(
                    f"Invalid geometry in row {n}. Check that all input geometries are "
                    f"valid before processing. Try using the check validity tool on "
                    f"the 'Vector' menu on the toolbar for more information on which "
                    f"features are invalid (Under 'Vector' - 'Geometry Tools' - "
                    f"'Check Validity')."
                )
            geometries.append(geom)
            n += 1
        return qgis.core.QgsGeometry.unaryUnion(geometries)

    @functools.lru_cache(
        maxsize=None
    )  # not using functools.cache, as it was only introduced in Python 3.9
    def meridian_split(self, out_type="extent", out_format="geojson", warn=True):
        """
        Return list of bounding boxes in WGS84 as geojson for GEE

        Returns multiple geometries as needed to avoid having an extent
        crossing the 180th meridian
        """

        # log("In meridian_split")
        # log(traceback.extract_tb().format()().format())

        if out_type not in ["extent", "layer"]:
            raise ValueError('Unrecognized out_type "{}"'.format(out_type))
        if out_format not in ["geojson", "wkt"]:
            raise ValueError('Unrecognized out_format "{}"'.format(out_format))

        union = self.get_unary_geometry()

        log(
            "Calculating east and west intersections to test if AOI crosses 180th meridian."
        )
        hemi_e = qgis.core.QgsGeometry.fromWkt(
            "POLYGON ((0 -90, 0 90, 180 90, 180 -90, 0 -90))"
        )
        hemi_w = qgis.core.QgsGeometry.fromWkt(
            "POLYGON ((-180 -90, -180 90, 0 90, 0 -90, -180 -90))"
        )
        intersections = [hemi.intersection(union) for hemi in [hemi_e, hemi_w]]

        if out_type == "extent":
            pieces = [
                qgis.core.QgsGeometry.fromRect(i.boundingBox())
                for i in intersections
                if not i.isEmpty()
            ]
        elif out_type == "layer":
            pieces = [i for i in intersections if not i.isEmpty()]
        pieces_union = qgis.core.QgsGeometry.unaryUnion(pieces)
        pieces_bounding = qgis.core.QgsGeometry.fromRect(pieces_union.boundingBox())

        if out_format == "geojson":
            pieces_txt = [json.loads(piece.asJson()) for piece in pieces]
            pieces_union_txt = json.loads(pieces_union.asJson())
        elif out_format == "wkt":
            pieces_txt = [piece.asWkt() for piece in pieces]
            pieces_union_txt = pieces_union.asWkt()

        total_pieces_area = sum([piece.area() for piece in pieces])
        if (not pieces_bounding.area() > total_pieces_area) and (
            (len(pieces) == 1) or (total_pieces_area > (pieces_union.area() / 2))
        ):
            # If there is no area in one of the hemispheres, return the
            # original layer, or extent of the original layer. Also return the
            # original layer (or extent) if the area of the combined pieces
            # from both hemispheres is not significantly smaller than that of
            # the original polygon.
            log("AOI being processed in one piece " "(does not cross 180th meridian)")
            return (False, [pieces_union_txt])
        else:
            log("AOI crosses 180th meridian - " "splitting AOI into two geojsons.")
            return (True, pieces_txt)

    def get_aligned_output_bounds(self, f):
        wkts = self.meridian_split(out_format="wkt", warn=False)[1]
        if not wkts:
            return None
        out = []
        for wkt in wkts:
            # Compute the pixel-aligned bounding box (slightly larger than
            # aoi).
            # Use this to set bounds in vrt files in order to keep the
            # pixels aligned with the chosen layer
            geom = ogr.CreateGeometryFromWkt(wkt)
            (minx, maxx, miny, maxy) = geom.GetEnvelope()
            gt = gdal.Open(f).GetGeoTransform()
            left = minx - (minx - gt[0]) % gt[1]
            right = maxx + (gt[1] - ((maxx - gt[0]) % gt[1]))
            bottom = miny + (gt[5] - ((miny - gt[3]) % gt[5]))
            top = maxy - (maxy - gt[3]) % gt[5]
            out.append([left, bottom, right, top])
        return out

    def get_aligned_output_bounds_deprecated(self, f):
        # Compute the pixel-aligned bounding box (slightly larger than aoi).
        # Use this to set bounds in vrt files in order to keep the
        # pixels aligned with the chosen layer
        bb = self.bounding_box_geom().boundingBox()
        minx = bb.xMinimum()
        miny = bb.yMinimum()
        maxx = bb.xMaximum()
        maxy = bb.yMaximum()
        gt = gdal.Open(f).GetGeoTransform()
        left = minx - (minx - gt[0]) % gt[1]
        right = maxx + (gt[1] - ((maxx - gt[0]) % gt[1]))
        bottom = miny + (gt[5] - ((miny - gt[3]) % gt[5]))
        top = maxy - (maxy - gt[3]) % gt[5]
        return [left, bottom, right, top]

    def get_area(self):
        wgs84_crs = qgis.core.QgsCoordinateReferenceSystem("EPSG:4326")

        # Returns area of aoi components in sq m
        wkts = self.meridian_split(out_format="wkt", warn=False)[1]
        if not wkts:
            return None
        area = 0.0
        for wkt in wkts:
            geom = qgis.core.QgsGeometry.fromWkt(wkt)
            # Lambert azimuthal equal area centered on polygon centroid
            centroid = geom.centroid().asPoint()
            laea_crs = qgis.core.QgsCoordinateReferenceSystem.fromProj(
                "+proj=laea +lat_0={} +lon_0={}".format(centroid.y(), centroid.x())
            )
            to_laea = qgis.core.QgsCoordinateTransform(
                wgs84_crs, laea_crs, qgis.core.QgsProject.instance()
            )
            geom.transform(to_laea)
            this_area = geom.area()
            area += this_area
        return area

    def get_layer(self):
        """
        Return layer
        """
        return self.l

    def get_crs_wkt(self):
        return self.l.sourceCrs().toWkt()

    def get_layer_wgs84(self):
        """
        Return layer in WGS84 (WPGS:4326)
        """
        # Setup settings for AOI provided to GEE:
        wgs84_crs = qgis.core.QgsCoordinateReferenceSystem()
        wgs84_crs.createFromProj("+proj=longlat +datum=WGS84 +no_defs")
        return _transform_layer(self.l, wgs84_crs, datatype=self.datatype, wrap=False)

    def bounding_box_geom(self):
        "Returns bounding box in chosen destination coordinate system"
        return qgis.core.QgsGeometry.fromRect(self.l.extent())

    def bounding_box_gee_geojson(self):
        """
        Returns two values - first is an indicator of whether this geojson
        includes two geometries due to crossing of the 180th meridian, and the
        second is the list of bounding box geojsons.
        """
        if self.datatype == "polygon":
            return self.meridian_split()
        elif self.datatype == "point":
            # If there is only on point, don't calculate an extent (extent of
            # one point is a box with sides equal to zero)
            n = 0
            for f in self.l.getFeatures():
                n += 1
                if n == 1:
                    # Save the first geometry in case it is needed later
                    # for a layer that only has one point in it
                    geom = f.geometry()
            if n == 1:
                log("Layer only has one point")
                return (False, [json.loads(geom.asJson())])
            else:
                log("Layer has many points ({})".format(n))
                return self.meridian_split()
        else:
            raise RuntimeError(
                f"Failed to process area of interest - unknown geometry "
                f"type: {self.datatype}"
            )

    def buffer(self, d):
        log("Buffering layer by {} km.".format(d))

        # Use correct transform direction enum based on version
        major_version, minor_version = _get_qgis_version()
        if major_version >= 3 and minor_version >= 22:
            trans_dir = qgis.core.Qgis.TransformDirection.Reverse
        else:
            trans_dir = (
                qgis.core.QgsCoordinateTransform.TransformDirection.ReverseTransform
            )

        feats = []
        for f in self.l.getFeatures():
            geom = f.geometry()
            # Setup an azimuthal equidistant projection centered on the polygon
            # centroid
            centroid = geom.centroid().asPoint()
            geom.centroid()
            wgs84_crs = qgis.core.QgsCoordinateReferenceSystem("EPSG:4326")
            aeqd_crs = qgis.core.QgsCoordinateReferenceSystem.fromProj(
                "+proj=aeqd +lat_0={} +lon_0={}".format(centroid.y(), centroid.x())
            )
            to_aeqd = qgis.core.QgsCoordinateTransform(
                wgs84_crs, aeqd_crs, qgis.core.QgsProject.instance()
            )
            geom.transform(to_aeqd)
            # Need to convert from km to meters
            geom_buffered = geom.buffer(d * 1000, 100)
            log(
                "Feature area in sq km after buffering (and in aeqd) is: {}".format(
                    geom_buffered.area() / (1000 * 1000)
                )
            )
            geom_buffered.transform(to_aeqd, trans_dir)
            f.setGeometry(geom_buffered)
            feats.append(f)
            log(
                "Feature area after buffering (and in WGS84) is: {}".format(
                    geom_buffered.area()
                )
            )

        l_buffered = qgis.core.QgsVectorLayer(
            "polygon?crs=proj4:{crs}".format(crs=self.l.crs().toProj()),
            "calculation boundary (transformed)",
            "memory",
        )
        l_buffered.dataProvider().addFeatures(feats)
        l_buffered.commitChanges()

        if not l_buffered.isValid():
            log("Error buffering layer")
            raise
        else:
            self.l = l_buffered
            self.datatype = "polygon"
        return True

    def isValid(self):
        return self.l.isValid()

    @functools.lru_cache(
        maxsize=None
    )  # not using functools.cache, as it was only introduced in Python 3.9
    def calc_frac_overlap(self, geom):
        """
        Returns fraction of AOI that is overlapped by geom (where geom is a QgsGeometry)

        Used to calculate "within" with a tolerance
        """
        _, aoi_wkts = self.meridian_split(out_type="extent", out_format="wkt")

        # Handle case of a point with zero area
        in_geom = ogr.CreateGeometryFromWkt(geom.asWkt())
        in_geom_area = in_geom.GetArea()
        if in_geom_area == 0:
            aoi_geom = ogr.CreateGeometryFromWkt(aoi_wkts)
            if aoi_geom.Within(in_geom):
                return 1

        total_aoi_area = 0
        area_covered = 0
        for aoi_wkt in aoi_wkts:
            # Need to allow for AOIs that may be split up into multiple parts due to 180thself.
            # So add up the fractions of the geom that each piece of the AOI covers
            aoi_geom = ogr.CreateGeometryFromWkt(aoi_wkt)
            total_aoi_area += aoi_geom.GetArea()

            # Calculate the area of this piece of the AOI that the input geom covers
            area_covered += aoi_geom.Intersection(in_geom).GetArea()
        try:
            return area_covered / total_aoi_area
        except ZeroDivisionError:
            log(
                f"Got ZeroDivisionError processing aoi wkts {aoi_wkts}. "
                "Returning 0 for area of overlap"
            )
            return 0

    def calc_disjoint(self, geom):
        """
        Returns whether a geom is disjoint with the AOI
        """
        _, aoi_wkts = self.meridian_split(out_type="extent", out_format="wkt")

        # Handle case of a point with zero area
        in_geom = ogr.CreateGeometryFromWkt(geom.asWkt())
        in_geom_area = in_geom.GetArea()
        if in_geom_area == 0:
            if aoi_geom.Within(in_geom):
                return False

        for aoi_wkt in aoi_wkts:
            # Need to allow for AOIs that may be split up into multiple parts due to 180th.
            aoi_geom = ogr.CreateGeometryFromWkt(aoi_wkt)
            if aoi_geom.Disjoint(in_geom):
                return True
        return False

    def get_geojson(self, split=False):
        geojson = {"type": "FeatureCollection", "features": []}

        if split:
            geojson["features"].append(
                self.meridian_split(out_type="layer", out_format="geojson")
            )
        else:
            n = 1
            for f in self.get_layer_wgs84().getFeatures():
                geom = f.geometry()
                if not geom.isGeosValid():
                    log("Invalid feature in row {}.".format(n))
                    QtWidgets.QMessageBox.critical(
                        None,
                        tr_areaofinterest.tr("Error"),
                        tr_areaofinterest.tr(
                            "Invalid geometry in row {}. "
                            "Check that all input geom_jsons "
                            "are valid before processing. "
                            "Try using the check validity "
                            'tool on the "Vector" menu on '
                            "the toolbar for more information "
                            "on which features are invalid "
                            '(Under "Vector" - "Geometry '
                            'Tools" - "Check Validity").'.format(n)
                        ),
                    )
                    return None
                geojson["features"].append(
                    {"type": "Feature", "geometry": json.loads(geom.asJson())}
                )
                n += 1
        return geojson


def qgs_error_message(error_title="Error", error_desciption="", timeout=0):
    """Displays an error message on the QGIS message bar. A button is included which will open
    the settings for the plugin.

    :param error_title: Error message title
    :type error_title: str

    :param error_desciption: Error message description
    :type error_desciption: str

    :param timeout: Message bar timeout in seconds. 0 is infinite.
    :type timeout: int
    """

    message_bar = qgisiface.messageBar()

    msg_widget = message_bar.createMessage(error_title, error_desciption)

    settings_btn = QtWidgets.QPushButton(msg_widget)
    settings_btn.setText("Settings")
    settings_btn.pressed.connect(open_settings)
    msg_widget.layout().addWidget(settings_btn)

    message_bar.pushWidget(msg_widget, level=Qgis.Info, duration=timeout)


def open_settings():
    """Opens the QGIS settings panel. The Trends.Earth tab will be selected."""
    qgisiface.showOptionsDialog(currentPage=conf.OPTIONS_TITLE)


def prepare_area_of_interest() -> AOI:
    if conf.settings_manager.get_value(conf.Setting.CUSTOM_CRS_ENABLED):
        crs_dst = qgis.core.QgsCoordinateReferenceSystem(
            conf.settings_manager.get_value(conf.Setting.CUSTOM_CRS)
        )
    else:
        crs_dst = qgis.core.QgsCoordinateReferenceSystem("epsg:4326")

    area_of_interest = AOI(crs_dst)
    area_method = conf.settings_manager.get_value(conf.Setting.AREA_FROM_OPTION)
    has_buffer = conf.settings_manager.get_value(conf.Setting.BUFFER_CHECKED)
    is_city = area_method == conf.AreaSetting.COUNTRY_CITY.value
    is_region = area_method == conf.AreaSetting.COUNTRY_REGION.value
    if is_city and not has_buffer:
        qgs_error_message(
            "Buffer required",
            "Calculations for cities require a buffer. This can be set in the Trend.Earth settings.",
            60,
        )
    elif is_city:
        geojson = get_city_geojson()
        area_of_interest.update_from_geojson(
            geojson=geojson, wrap=False, datatype="point"
        )
    elif is_region:
        geojson, error_msg = validate_country_region()
        if geojson is None:
            raise RuntimeError(error_msg)
        area_of_interest.update_from_geojson(
            geojson=geojson, wrap=False  # FIXME: add the corresponding setting
        )
    elif area_method == conf.AreaSetting.VECTOR_LAYER.value:
        vector_path, error_msg = validate_vector_path()
        if vector_path is None:
            raise RuntimeError(error_msg)
        area_of_interest.update_from_file(
            f=conf.settings_manager.get_value(conf.Setting.VECTOR_FILE_PATH),
            wrap=False,  # FIXME: add the corresponding setting
        )
    elif area_method == conf.AreaSetting.POINT.value:
        # Area from point
        point_x = conf.settings_manager.get_value(conf.Setting.POINT_X)
        point_y = conf.settings_manager.get_value(conf.Setting.POINT_Y)
        if point_x is None or point_y is None:
            raise RuntimeError(f"Invalid point coordinates: {point_x!r}, {point_y!r}")
        point = qgis.core.QgsPointXY(float(point_x), float(point_y))
        crs_src = qgis.core.QgsCoordinateReferenceSystem("epsg:4326")
        point = qgis.core.QgsCoordinateTransform(
            crs_src, crs_dst, qgis.core.QgsProject.instance()
        ).transform(point)
        geojson = json.loads(qgis.core.QgsGeometry.fromPointXY(point).asJson())
        area_of_interest.update_from_geojson(
            geojson=geojson,
            wrap=False,  # FIXME: add the corresponding setting
            datatype="point",
        )
    else:
        raise RuntimeError("Choose an area of interest")

    is_valid = area_of_interest.isValid()
    if area_of_interest and (area_of_interest.datatype == "unknown" or not is_valid):
        raise RuntimeError("Unable to read area of interest.")

    if has_buffer:
        buffer_size = conf.settings_manager.get_value(conf.Setting.BUFFER_SIZE)
        ret = area_of_interest.buffer(float(buffer_size))
        if not ret:
            raise RuntimeError("Error buffering polygon")

    # Limit processing area to be no greater than 10^7 sq km if using a
    # custom shapefile
    max_area: int = 5e7  # maximum size task the tool supports
    if not is_city and not is_region:
        aoi_area = area_of_interest.get_area() / (1000 * 1000)
        if aoi_area > max_area:
            raise RuntimeError(
                "The bounding box for the requested area (approximately {:.6n}) sq km "
                "is too large. Choose a smaller area to process.".format(aoi_area)
            )
    return area_of_interest


def get_aligned_output_bounds(f, wkt_bounding_boxes):
    out = []
    for wkt in wkt_bounding_boxes:
        # Compute the pixel-aligned bounding box (slightly larger than
        # aoi).
        # Use this to set bounds in vrt files in order to keep the
        # pixels aligned with the chosen layer
        geom = ogr.CreateGeometryFromWkt(wkt)
        (minx, maxx, miny, maxy) = geom.GetEnvelope()
        gt = gdal.Open(f).GetGeoTransform()
        left = minx - (minx - gt[0]) % gt[1]
        right = maxx + (gt[1] - ((maxx - gt[0]) % gt[1]))
        bottom = miny + (gt[5] - ((miny - gt[3]) % gt[5]))
        top = maxy - (maxy - gt[3]) % gt[5]
        out.append([left, bottom, right, top])
    return out


def _transform_layer(l, crs_dst, datatype="polygon", wrap=False):
    # Transform CRS of a layer while optionally wrapping geometries
    # across the 180th meridian
    log(
        'Transforming layer from "{}" to "{}". Wrap is {}. Datatype is {}.'.format(
            l.crs().toProj(), crs_dst.toProj(), wrap, datatype
        )
    )

    crs_src_string = l.crs().toProj()
    if wrap:
        if not l.crs().isGeographic():
            QtWidgets.QMessageBox.critical(
                None,
                tr_areaofinterest.tr("Error"),
                tr_areaofinterest.tr(
                    "Error - layer is not in a geographic coordinate system. "
                    "Cannot wrap layer across 180th meridian."
                ),
            )
            log(
                'Can\'t wrap layer in non-geographic coordinate system: "{}"'.format(
                    crs_src_string
                )
            )
            return None
        crs_src_string = crs_src_string + " +lon_wrap=180"
    crs_src = qgis.core.QgsCoordinateReferenceSystem()
    crs_src.createFromProj(crs_src_string)
    t = qgis.core.QgsCoordinateTransform(
        crs_src, crs_dst, qgis.core.QgsProject.instance()
    )

    l_w = qgis.core.QgsVectorLayer(
        "{datatype}?crs=proj4:{crs}".format(datatype=datatype, crs=crs_dst.toProj()),
        "calculation boundary (transformed)",
        "memory",
    )
    feats = []
    for f in l.getFeatures():
        geom = f.geometry()
        if wrap:
            n = 0
            p = geom.vertexAt(n)
            # Note vertexAt returns QgsPointXY(0, 0) on error
            while p != qgis.core.QgsPointXY(0, 0):
                if p.x() < 0:
                    geom.moveVertex(p.x() + 360, p.y(), n)
                n += 1
                p = geom.vertexAt(n)
        geom.transform(t)
        f.setGeometry(geom)
        feats.append(f)
    l_w.dataProvider().addFeatures(feats)
    l_w.commitChanges()
    if not l_w.isValid():
        log(
            'Error transforming layer from "{}" to "{}" (wrap is {})'.format(
                crs_src_string, crs_dst.toProj(), wrap
            )
        )
        return None
    else:
        return l_w
