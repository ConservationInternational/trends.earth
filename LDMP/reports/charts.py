"""Charts showing summary layer statistics."""

import os
import typing
from collections import namedtuple
from dataclasses import field
from enum import Enum

import numpy as np
import plotly.graph_objects as go
from qgis import processing
from qgis.core import (
    QgsColorRampShader,
    QgsDistanceArea,
    QgsGeometry,
    QgsLayoutExporter,
    QgsLayoutFrame,
    QgsLayoutItemHtml,
    QgsLayoutMeasurement,
    QgsLayoutMeasurementConverter,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsPrintLayout,
    QgsProject,
    QgsUnitTypes,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication, QObject, Qt, QTemporaryFile, QUrl
from qgis.PyQt.QtGui import QColor

from ..jobs.models import Job
from ..layers import (
    create_categorical_color_ramp,
    create_categorical_color_ramp_from_legend,
    create_categorical_transitions_color_ramp_from_legend,
    create_categorical_with_dynamic_ramp_color_ramp,
    styles,
)
from .models import slugify


class tr_reports_charts(QObject):
    def tr(self, txt):
        return QCoreApplication.translate(self.__class__.__name__, txt)


tr_reports_charts = tr_reports_charts()

# Contains information about a layer and source band_info
LayerBandInfo = namedtuple("LayerBandInfo", "layer band_info")

# Statistical information for a single classification category
UniqueValuesInfo = namedtuple(
    "UniqueValuesInfo",
    "area category_label category_value color count coverage_percent",
)


class BaseChart:
    """
    Abstract class for a statistical chart.
    """

    def __init__(self, **kwargs):
        self.layer_band_info = kwargs.pop("layer_band_info", None)
        self.root_output_dir = kwargs.pop("root_output_dir", "")
        self._paths = []
        self._dpi = 300
        self._measurement_converter = QgsLayoutMeasurementConverter()
        self._measurement_converter.setDpi(self._dpi)

        # Try to maintain 4:3 aspect ratio
        self._width_mm = 280
        self._height_mm = 210

        self.plot_title = ""
        # Will be prefixed with 'chart-' in the file name.
        self.base_chart_name = ""

        self.font_size_legend = 18
        self.font_size_title = 30
        self.font_size_body = 14

        self.value_axis_label = ""

    @classmethod
    def warning_msg(cls, msg: str) -> str:
        # Append class name to the message.
        cls_name = cls.__class__.__name__
        return f"{cls_name}: {msg}"

    @property
    def paths(self) -> typing.List[str]:
        """
        Returns the absolute paths to the images. This is only populated
        once the chart(s) have been exported successfully.
        """
        return self._paths

    @classmethod
    def year(cls, band_info: dict) -> int:
        """
        Returns the year specified in the given band_info.
        """
        return band_info["metadata"]["year"]

    def layer_name(self) -> str:
        """
        Returns the layer name that can be used when naming the output files.
        """
        layer = self.layer_band_info.layer
        if layer is None:
            return ""

        return slugify(layer.name())

    @property
    def preferred_size(self) -> typing.Tuple[int, int]:
        """
        Returns the preferred width and height for the chart figure.
        Values are in pixels.
        """
        return 1058, 794

    def export(self) -> typing.Tuple[bool, list]:
        """
        Exports the chart to an image in the given root output directory.
        Returns True if the process was successful, else False. Includes a
        list of warning messages that occurred during the export process.
        Needs to be implemented by sub-classes.
        """
        raise NotImplementedError

    def mm_to_pixels(self, length: float) -> float:
        """
        Converts length measurement to equivalent pixels taking into account
        the resolution.
        """
        measurement = QgsLayoutMeasurement(length, QgsUnitTypes.LayoutMillimeters)
        pix_measurement = self._measurement_converter.convert(
            measurement, QgsUnitTypes.LayoutPixels
        )

        return pix_measurement.length()

    def _chart_layout(self, chart_path: str) -> QgsPrintLayout:
        # Layout container for exporting chart to image.
        layout = QgsPrintLayout(QgsProject.instance())
        layout.initializeDefaults()
        layout.renderContext().setDpi(self._dpi)

        # Add html item
        html_item = QgsLayoutItemHtml(layout)
        frame = QgsLayoutFrame(layout, html_item)
        html_item.addFrame(frame)
        frame.attemptMove(QgsLayoutPoint(16, 0, QgsUnitTypes.LayoutMillimeters))
        frame.attemptResize(QgsLayoutSize(280, 210))
        layout.addMultiFrame(html_item)

        url = QUrl.fromLocalFile(chart_path)
        html_item.setUrl(url)

        return layout

    def save_image(self, figure: go.Figure, path: str) -> bool:
        """
        Save the figure as an image file. While plotly supports writing a
        Figure object to an image, it requires additional libraries which
        are not shipped with the QGIS Python package, and since we are
        avoiding additional dependencies, we will use the layout framework
        for image export.
        """
        pw, ph = self.preferred_size
        figure.update_layout(width=pw, height=ph)

        temp_html_file = QTemporaryFile()
        if not temp_html_file.open():
            return False

        file_name = temp_html_file.fileName()
        html_path = f"{file_name}.html"

        # Write figure to html
        figure.write_html(
            html_path,
            auto_open=False,
            auto_play=False,
            config={"displayModeBar": False},
        )

        # Create and export layout
        layout = self._chart_layout(html_path)
        exporter = QgsLayoutExporter(layout)
        settings = QgsLayoutExporter.ImageExportSettings()
        res = exporter.exportToImage(path, settings)

        if res != QgsLayoutExporter.Success:
            return False

        return True


class InfoValueType(Enum):
    """
    Value to use for plotting in UniqueValueInfo object.
    """

    AREA = 0
    PERCENT = 1


class BaseUniqueValuesChart(BaseChart):
    """
    Provides an interface for getting the statistics of each pixel value for
    a given band in a raster layer.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.band_number = -1
        self.value_info_collection = []
        self.use_value_type = InfoValueType.AREA

    @classmethod
    def report(
        cls, layer_band_info: LayerBandInfo, band_number: int
    ) -> typing.List[UniqueValuesInfo]:
        """
        Returns a list containing area count for each unique pixel
        value for the given band.
        """
        layer = layer_band_info.layer
        band_info = layer_band_info.band_info
        band_info_name = band_info["name"]
        idx_clr_ramp = _create_indexed_color_ramp(band_info_name, band_info)

        output_temp_file = QTemporaryFile()
        if not output_temp_file.open():
            return []

        if band_number < 1 or band_number > layer.bandCount():
            return []

        file_name = output_temp_file.fileName()

        alg_name = "native:rasterlayeruniquevaluesreport"
        output_table = f"{file_name}.geojson"
        params = {"INPUT": layer, "BAND": band_number, "OUTPUT_TABLE": output_table}

        output = processing.run(alg_name, params)

        # Compute pixel size in sq km
        pixel_count = output["TOTAL_PIXEL_COUNT"]
        area_calc = QgsDistanceArea()
        area_calc.setEllipsoid("WGS84")
        ext_geom = QgsGeometry.fromRect(layer.extent())
        extents_area = area_calc.measureArea(ext_geom)
        area_km = area_calc.convertAreaMeasurement(
            extents_area, QgsUnitTypes.AreaSquareKilometers
        )
        pixel_area = area_km / pixel_count

        unique_vals = []

        vl = QgsVectorLayer(output_table)
        feat_iter = vl.getFeatures()

        for f in feat_iter:
            pix_val = f["value"]
            num_pixels = f["count"]
            area_sq_km = num_pixels * pixel_area
            area_percent = area_sq_km / area_km * 100

            # Get label and color defined in the band style
            label = ""
            clr = Qt.lightGray
            int_pix_val = int(pix_val)
            if int_pix_val in idx_clr_ramp:
                ramp_item = idx_clr_ramp[int_pix_val]
                label = ramp_item.label
                clr = ramp_item.color

            vi = UniqueValuesInfo(
                area_sq_km, label, pix_val, clr, num_pixels, area_percent
            )
            unique_vals.append(vi)

        return unique_vals


class UniqueValuesPieChart(BaseUniqueValuesChart):
    """
    Plots the pixel stats in a pie chart.
    """

    def export(self) -> typing.Tuple[bool, list]:
        # Create stats pie chart
        if not self.root_output_dir:
            return False, ["Output directory not defined"]

        if self.band_number < 1 and len(self.value_info_collection) == 0:
            return False, ["Band number cannot be less than one"]

        # If unique values collection is empty then extract from the layer.
        if len(self.value_info_collection) == 0:
            self.value_info_collection = self.report(
                self.layer_band_info, self.band_number
            )

        file_name_base = self.base_chart_name
        if not file_name_base:
            file_name_base = self.layer_name()

        output_file_path = f"{self.root_output_dir}/chart-{file_name_base}.png"

        labels = []
        values = []
        colors = []
        for val_info in self.value_info_collection:
            # Remove pixel value prefix
            lbls = val_info.category_label.split("-", maxsplit=1)
            label = lbls[0] if len(lbls) == 1 else lbls[1]

            labels.append(label)
            values.append(round(val_info.area))
            colors.append(val_info.color.name())

        pw, ph = self.preferred_size

        text_info = "value"
        if self.use_value_type == InfoValueType.PERCENT:
            text_info = "percent"

        # Create and export pie chart
        fig = go.Figure(data=[go.Pie(labels=labels, values=values)])
        fig.update_traces(
            textinfo=text_info,
            marker=dict(colors=colors),
            textfont={"size": self.font_size_body},
        )
        fig.update_layout(
            title={
                "text": self.plot_title,
                "y": 0.95,
                "x": 0.5,
                "xanchor": "center",
                "yanchor": "top",
                "font": {"size": self.font_size_title},
            },
            legend={"font": {"size": self.font_size_legend}},
            width=pw,
            height=ph,
        )

        # Save image
        self.save_image(fig, output_file_path)
        self._paths.append(output_file_path)

        return True, []


class ChangeBarChartType(Enum):
    """
    Type of change barchart types to plot.
    """

    CLUSTERED = 0
    POS_NEG = 1
    ALL = 2


class UniqueValuesChangeBarChart(BaseUniqueValuesChart):
    """
    Plots both clustered and positive/negative bar graphs.
    """

    def __init__(self, **kwargs):
        self.target_layer_band_info = kwargs.pop("target_lbi", None)
        self.target_band_number = kwargs.pop("target_band", -1)
        self.target_value_info_collection = []
        self.chart_type = ChangeBarChartType.ALL
        super().__init__(**kwargs)

        self.init_year = None
        self.target_year = None

        if self.layer_band_info:
            self.init_year = self.year(self.layer_band_info.band_info)

        if self.target_layer_band_info:
            self.target_year = self.year(self.target_layer_band_info.band_info)

    def export(self) -> typing.Tuple[bool, list]:
        # Create clustered bar graph comparing initial and target years.
        if not self.root_output_dir:
            return False, ["Output directory not defined"]

        if self.band_number < 1 and len(self.value_info_collection) == 0:
            return False, ["Initial band number cannot be less than one."]

        if self.target_band_number < 1 and len(self.target_value_info_collection) == 0:
            return False, ["Target band number must cannot be less than one."]

        # Initial value info collection
        if len(self.value_info_collection) == 0:
            self.value_info_collection = self.report(
                self.layer_band_info, self.band_number
            )

        # Target (year) value info collection
        if len(self.target_value_info_collection) == 0:
            self.target_value_info_collection = self.report(
                self.target_layer_band_info, self.target_band_number
            )

        file_name = slugify(f"chart-{self.base_chart_name}_area")
        output_file_path = f"{self.root_output_dir}/{file_name}.png"

        labels = []
        init_values = []
        target_values = []
        init_colors = []
        target_colors = []
        for i in range(len(self.value_info_collection)):
            init_val_info = self.value_info_collection[i]
            target_val_info = self.target_value_info_collection[i]

            # Labels
            lbls = init_val_info.category_label.split("-", maxsplit=1)
            label = lbls[0] if len(lbls) == 1 else lbls[1]
            labels.append(label)

            # Area
            init_values.append(round(init_val_info.area))
            target_values.append(round(target_val_info.area))

            # Colors
            target_clr = target_val_info.color
            init_clr = target_clr.lighter(128)
            init_colors.append(init_clr.name())
            target_colors.append(target_clr.name())

        # Preferred chart size
        pw, ph = self.preferred_size

        # Create and export grouped bar graph
        if (
            self.chart_type == ChangeBarChartType.CLUSTERED
            or self.chart_type == ChangeBarChartType.ALL
        ):
            fig = go.Figure()
            # Init year
            fig.add_trace(
                go.Bar(
                    x=labels,
                    y=init_values,
                    name=str(self.init_year),
                    marker_color=init_colors,
                    text=init_values,
                    textposition="auto",
                    texttemplate="%{y:,.4r}",
                    textfont={"size": 10},
                )
            )
            # Target year
            fig.add_trace(
                go.Bar(
                    x=labels,
                    y=target_values,
                    name=str(self.target_year),
                    marker_color=target_colors,
                    text=target_values,
                    textposition="auto",
                    texttemplate="%{y:,.4r}",
                    textfont={"size": 10},
                )
            )

            fig.update_layout(
                title={
                    "text": self.plot_title,
                    "y": 0.95,
                    "x": 0.5,
                    "xanchor": "center",
                    "yanchor": "top",
                    "font": {"size": self.font_size_title},
                },
                xaxis={"tickfont_size": self.font_size_body},
                yaxis={
                    "title": self.value_axis_label,
                    "titlefont_size": self.font_size_legend,
                    "tickfont_size": self.font_size_body,
                    "tickformat": ",.4r",
                },
                barmode="group",
                bargap=0.15,
                bargroupgap=0.1,
                showlegend=False,
                width=pw,
                height=ph,
            )

            # Save image
            self.save_image(fig, output_file_path)
            self._paths.append(output_file_path)

        # Positive/negative bar graph
        if (
            self.chart_type == ChangeBarChartType.POS_NEG
            or self.chart_type == ChangeBarChartType.ALL
        ):
            # Update properties depending on whether to show area or percent
            # ia - init area, ta - target area
            def change_func(ia, ta):
                return ta - ia

            text_template = "%{y:,.4r}"

            # Percent
            if self.use_value_type == InfoValueType.PERCENT:

                def change_func(ia, ta):
                    return (ta - ia) * 100 / ia

                text_template = "%{y:.2f}%"
                if not self.value_axis_label:
                    self.value_axis_label = "%"

            change_val = list(map(change_func, init_values, target_values))

            # Create and export figure
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    y=change_val,
                    x=labels,
                    marker_color=target_colors,
                    text=change_val,
                    texttemplate=text_template,
                    textposition="outside",
                    textfont={"size": self.font_size_body},
                )
            )
            fig.update_layout(
                title={
                    "text": self.plot_title,
                    "y": 0.95,
                    "x": 0.5,
                    "xanchor": "center",
                    "yanchor": "top",
                    "font": {"size": self.font_size_title},
                },
                yaxis={
                    "tickfont_size": self.font_size_body,
                    "title": self.value_axis_label,
                },
                xaxis={"tickfont_size": self.font_size_body},
                showlegend=False,
                width=pw,
                height=ph,
            )

            # Export
            file_name = slugify(f"chart-{self.base_chart_name}_percent")
            output_file_path = f"{self.root_output_dir}/{file_name}.png"

            # Save image
            self.save_image(fig, output_file_path)
            self._paths.append(output_file_path)

        return True, []


class StackedBarChart(BaseChart):
    """
    Stacked bar chart.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Key contains x-axis label, value is a list of UniqueValueInfo
        # objects.
        self.data_items = {}

        self.use_value_type = InfoValueType.AREA
        self.font_size_labels = 12

    def export(self) -> typing.Tuple[bool, list]:
        # Create chart
        if not self.root_output_dir:
            return False, ["Output directory not defined"]

        if len(self.data_items) == 0:
            return False, ["No data items defined."]

        file_name = slugify(f"chart-{self.base_chart_name}")
        output_file_path = f"{self.root_output_dir}/{file_name}.png"

        # Re-arrange elements so that each iterable contains single item
        # category spread across the items in the keys or x-axis.
        grouped_items = list(zip(*self.data_items.values()))
        labels = list(self.data_items.keys())

        # Preferred chart size
        pw, ph = self.preferred_size

        # Create and export stacked bar graph
        fig = go.Figure()
        for lc_infos in grouped_items:
            values = []
            color = None
            series_name = None
            for lci in lc_infos:
                if self.use_value_type == InfoValueType.AREA:
                    values.append(lci.area)
                else:
                    values.append(lci.coverage_percent)
                if color is None:
                    color = lci.color.name()

                if series_name is None:
                    series_name = lci.category_label

            fig.add_trace(
                go.Bar(
                    x=labels,
                    y=values,
                    name=series_name,
                    textposition="inside",
                    texttemplate="%{y:,.2f}",
                    marker_color=color,
                    textfont={"size": self.font_size_labels},
                )
            )

        fig.update_layout(
            title={
                "text": self.plot_title,
                "y": 0.95,
                "x": 0.5,
                "xanchor": "center",
                "yanchor": "top",
                "font": {"size": self.font_size_title},
            },
            xaxis={"tickfont_size": self.font_size_body},
            yaxis={
                "title": self.value_axis_label,
                "tickfont_size": self.font_size_body,
                "tickformat": ",.4r",
            },
            legend={"font": {"size": self.font_size_legend}},
            uniformtext={"minsize": 7, "mode": "hide"},
            barmode="relative",
            showlegend=True,
            width=pw,
            height=ph,
        )

        # Save image
        self.save_image(fig, output_file_path)
        self._paths.append(output_file_path)

        return True, []


class BaseAlgorithmChartsConfiguration:
    """
    Specifies the charts for a given algorithm, will produce charts for a
    given job.
    """

    layer_band_infos: typing.List[LayerBandInfo] = field(default_factory=list)

    def __init__(self, job: Job, layer_band_infos, **kwargs):
        self.job = job
        self.layer_band_infos = layer_band_infos
        self._root_output_dir = kwargs.pop("root_output_dir", "")
        self._charts = []
        self._add_charts()

    @property
    def output_directory(self) -> str:
        """
        Returns the root output directory.
        """
        return self._root_output_dir

    @output_directory.setter
    def output_directory(self, path: str):
        """
        Sets the root output directory and cascades this to the chart objects.
        """
        self._root_output_dir = path
        for c in self._charts:
            c.root_output_dir = path

    def _add_charts(self):
        """
        Specify the charts to be used by the configuration. Should be
        implemented by sub-classes.
        """
        raise NotImplementedError

    def generate(self) -> typing.Tuple[bool, list]:
        """
        Saves the charts to file. Returns False if one or more of the
        chart exports failed. Also includes a list containing warning
        messages from one or more charts.
        """
        if not self._root_output_dir:
            return False, ["Output directory not specified"]

        if not os.path.exists(self._root_output_dir):
            return False, ["Output directory does not exist"]

        status = True
        messages = []
        for c in self._charts:
            res, msgs = c.export()
            if not res:
                status = False
                if len(msgs) > 0:
                    messages.extend(msgs)

        # Append class name to the messages
        cls_name = self.__class__.__name__
        fmt_msgs = map(lambda msg: f"{cls_name} - {msg}", messages)

        return status, list(fmt_msgs)


def land_cover_title(year) -> str:
    """
    Translatable title for land cover charts.
    """
    tr_base_title = tr_reports_charts.tr("Land Cover Area")
    tr_in = tr_reports_charts.tr("in")

    return f"{tr_base_title} (km<sup>2</sup>) {tr_in} {year!s}"


class LandCoverChartsConfiguration(BaseAlgorithmChartsConfiguration):
    """
    Charts for land cover layers.
    """

    def _add_charts(self):
        if len(self.layer_band_infos) == 0:
            return

        # Get land cover band_infos
        lc_layer_band_infos = {}
        for lbi in self.layer_band_infos:
            bi = lbi.band_info
            bi_name = bi["name"]
            if bi_name in ["Land cover", "Land cover (7 class)"]:
                year = bi["metadata"]["year"]
                lc_layer_band_infos[year] = lbi

        sorted_lc_layer_band_infos = dict(sorted(lc_layer_band_infos.items()))
        sorted_band_infos = list(sorted_lc_layer_band_infos.values())
        init_layer_band_info = sorted_band_infos[0]
        target_layer_band_info = sorted_band_infos[1]

        init_band_num = 5
        target_band_num = 19

        init_yr_pie_chart = UniqueValuesPieChart(
            layer_band_info=init_layer_band_info, root_output_dir=self._root_output_dir
        )
        init_year = init_yr_pie_chart.year(init_layer_band_info.band_info)
        init_yr_pie_chart.plot_title = land_cover_title(init_year)
        init_yr_pie_chart.band_number = init_band_num

        self._charts.append(init_yr_pie_chart)

        target_yr_pie_chart = UniqueValuesPieChart(
            layer_band_info=target_layer_band_info,
            root_output_dir=self._root_output_dir,
        )
        target_year = target_yr_pie_chart.year(target_layer_band_info.band_info)
        target_yr_pie_chart.plot_title = land_cover_title(target_year)
        target_yr_pie_chart.band_number = target_band_num
        self._charts.append(target_yr_pie_chart)

        # Add clustered bar graph
        lc_change_barchart = UniqueValuesChangeBarChart(
            layer_band_info=init_layer_band_info,
            target_lbi=target_layer_band_info,
            root_output_dir=self._root_output_dir,
        )
        lc_change_barchart.band_number = init_band_num
        lc_change_barchart.target_band_number = target_band_num
        self._charts.append(lc_change_barchart)


class SdgSummaryChartsConfiguration(BaseAlgorithmChartsConfiguration):
    """
    Charts for SDG 15.3.1 summary.
    """

    def _add_charts(self):
        # Charts for SDG 15.3.1 (sub)indicators
        job_attr = SdgSummaryJobAttributes(self.job)

        summary_area_collection = job_attr.summary_area()

        base_title_tr = tr_reports_charts.tr("Summary of SDG 15.3.1 Indicator")
        base_chart_name = "sdg_15_3_1_summary"

        # Pie chart for summary indicator in area
        pie_chart_summary_area = UniqueValuesPieChart(
            root_output_dir=self._root_output_dir
        )
        title_area = f"{base_title_tr} (km<sup>2</sup>)"
        pie_chart_summary_area.plot_title = title_area
        pie_chart_summary_area.value_info_collection = summary_area_collection
        pie_chart_summary_area.base_chart_name = f"{base_chart_name}_area"

        self._charts.append(pie_chart_summary_area)

        # Period
        init_year, final_year = job_attr.period()

        # Init and final year value info collection
        init_lc_value_info_collection = job_attr.land_cover(str(init_year))
        final_lc_value_info_collection = job_attr.land_cover(str(final_year))

        # Pie chart for land cover in the initial year
        pie_chart_lc_init_year = UniqueValuesPieChart(
            root_output_dir=self._root_output_dir
        )
        pie_chart_lc_init_year.plot_title = land_cover_title(init_year)
        pie_chart_lc_init_year.value_info_collection = init_lc_value_info_collection
        pie_chart_lc_init_year.base_chart_name = f"land_cover_{init_year!s}"

        self._charts.append(pie_chart_lc_init_year)

        # Pie chart for land cover in the final year
        pie_chart_lc_final_year = UniqueValuesPieChart(
            root_output_dir=self._root_output_dir
        )
        pie_chart_lc_final_year.plot_title = land_cover_title(final_year)
        pie_chart_lc_final_year.value_info_collection = final_lc_value_info_collection
        pie_chart_lc_final_year.base_chart_name = f"land_cover_{final_year!s}"

        self._charts.append(pie_chart_lc_final_year)

        tr_lc_change = tr_reports_charts.tr("Change in Land Cover")
        lc_change_title = f"{tr_lc_change} (km<sup>2</sup>)"
        lc_chart_base_name = f"land-cover-changes-{init_year!s}-{final_year!s}"

        # Add positive/negative land cover bar graph
        lc_change_barchart = UniqueValuesChangeBarChart(
            root_output_dir=self._root_output_dir
        )
        lc_change_barchart.chart_type = ChangeBarChartType.POS_NEG
        lc_change_barchart.value_info_collection = init_lc_value_info_collection
        lc_change_barchart.target_value_info_collection = final_lc_value_info_collection
        lc_change_barchart.init_year = init_year
        lc_change_barchart.target_year = final_year
        lc_change_barchart.plot_title = lc_change_title
        lc_change_barchart.base_chart_name = lc_chart_base_name
        lc_change_barchart.value_axis_label = "km<sup>2</sup>"
        lc_change_barchart.use_value_type = InfoValueType.AREA
        self._charts.append(lc_change_barchart)

        # Init and final year soc value info collection
        init_soc_value_info_collection = job_attr.soc(str(init_year))
        final_soc_value_info_collection = job_attr.soc(str(final_year))

        tr_soc_change = tr_reports_charts.tr("Change in Soil Organic Carbon (Tonnes)")
        soc_chart_base_name = f"soc-changes-{init_year!s}-{final_year!s}"

        # Add positive/negative soil organic carbon bar graph
        soc_change_barchart = UniqueValuesChangeBarChart(
            root_output_dir=self._root_output_dir
        )
        soc_change_barchart.chart_type = ChangeBarChartType.POS_NEG
        soc_change_barchart.value_info_collection = init_soc_value_info_collection
        soc_change_barchart.target_value_info_collection = (
            final_soc_value_info_collection
        )
        soc_change_barchart.init_year = init_year
        soc_change_barchart.target_year = final_year
        soc_change_barchart.plot_title = tr_soc_change
        soc_change_barchart.base_chart_name = soc_chart_base_name
        soc_change_barchart.value_axis_label = tr_reports_charts.tr("Tonnes")
        soc_change_barchart.use_value_type = InfoValueType.AREA
        self._charts.append(soc_change_barchart)

        # LC productivity data
        lc_prod_info_items = job_attr.lc_by_productivity()

        tr_lc_productivity_title = tr_reports_charts.tr(
            "Land Cover Change by Productivity Class"
        )

        # Add productivity stacked bar graph
        productivity_barchart = StackedBarChart(root_output_dir=self._root_output_dir)
        productivity_barchart.plot_title = tr_lc_productivity_title
        productivity_barchart.data_items = lc_prod_info_items
        productivity_barchart.use_value_type = InfoValueType.PERCENT
        productivity_barchart.base_chart_name = (
            f"land-cover-change-by-productivity-{init_year!s}-{final_year!s}"
        )
        productivity_barchart.value_axis_label = tr_reports_charts.tr("%")
        self._charts.append(productivity_barchart)


class AlgorithmChartsManager:
    """
    Manages collection of algorithm configurations. Should be used as the
    main entry point when adding job layers and subsequently, generating
    charts.
    """

    def __init__(self, **kwargs):
        self._alg_charts_config_types = {}
        self._job_chart_configs = []
        self._root_output_dir = kwargs.pop("root_output_dir", "")
        self._set_default_chart_config_types()
        self._messages = []

    @property
    def output_dir(self) -> str:
        """
        Returns the root output directory.
        """
        return self._root_output_dir

    @output_dir.setter
    def output_dir(self, path: str):
        # Sets the root output directory
        self._root_output_dir = path
        for jcc in self._job_chart_configs:
            jcc.output_directory = path

    def _set_default_chart_config_types(self):
        """
        Set config for known algorithms.
        """
        self.add_alg_chart_config("land-cover", LandCoverChartsConfiguration)
        self.add_alg_chart_config("sdg-15-3-1-summary", SdgSummaryChartsConfiguration)

    def add_alg_chart_config(
        self, alg_name: str, chart_config: typing.Type[BaseAlgorithmChartsConfiguration]
    ) -> bool:
        """
        Specify the chart configuration class (not instance) for a given
        algorithm. Any existing configuration class for a given algorithm
        will replaced.
        """
        try:
            if not issubclass(chart_config, BaseAlgorithmChartsConfiguration):
                return False
        except TypeError:
            return False

        self._alg_charts_config_types[alg_name] = chart_config

        return True

    def alg_chart_config_by_name(
        self, alg_name: str
    ) -> typing.Type[BaseAlgorithmChartsConfiguration]:
        """
        Returns the chart configuration class for the given algorithm, else None.
        """
        return self._alg_charts_config_types.get(alg_name, None)

    @property
    def messages(self) -> typing.List[str]:
        """
        Returns a list of warning and error messages logged from the last run
        of generating charts.
        """
        return self._messages

    def add_job_layers(self, job: Job, band_infos: typing.List[LayerBandInfo]) -> bool:
        """
        Add job-band_info mapping. If the algorithm for the job does not have
        a corresponding mapped chart configuration, it will return False.
        """
        alg_name = job.script.name

        chart_config_cls = self.alg_chart_config_by_name(alg_name)
        if chart_config_cls is None:
            return False

        chart_config_obj = chart_config_cls(
            job, band_infos, root_output_dir=self._root_output_dir
        )
        self._job_chart_configs.append(chart_config_obj)

        return True

    def get_chart_config_by_job(self, job: Job) -> BaseAlgorithmChartsConfiguration:
        """
        Return the chart configuration object for the given job, else None.
        """
        configs = [c for c in self._job_chart_configs if c.job.id == job.id]
        if len(configs) == 0:
            return None

        return configs[0]

    def generate_charts(self) -> bool:
        """
        Generate and export charts for each configuration. Returns False if
        there was an error in producing one or more charts.
        """
        status = True
        self._messages = []

        for jcc in self._job_chart_configs:
            res, msgs = jcc.generate()
            if not res:
                status = False

            self._messages.extend(msgs)

        return status


class SdgSummaryJobAttributes:
    """
    Reads required job attributes for rendering summary SDG 15.3.1 charts.
    """

    def __init__(self, job: Job):
        self._job = job
        self._params_baseline = {}

        periods = self._job.params.get("periods", [])
        for period in periods:
            if period.get("name") == "baseline":
                self._params_baseline = period.get("params", {})
                break

        self._data = self._job.results.data
        self._baseline_results = (
            self._data.get("report", {})
            .get("land_condition", {})
            .get("baseline", {})
            .get("period_assessment", {})
        )

    def period(self) -> typing.Tuple[int, int]:
        # Initial year and final year
        period = self._params_baseline["period"]

        return period["year_initial"], period["year_final"]

    @classmethod
    def summary_indicator_str_value_mapping(cls) -> typing.Dict[str, int]:
        return {"Improved": 1, "Stable": 0, "Degraded": -1, "No data": -32768}

    def land_cover_7_class_str_info_mapping(self) -> typing.Dict[str, int]:
        # Returns a collection of land cover class info (name, color, code)
        # indexed by the category name.
        lc_mapping = {}

        legend_parent = self._baseline_results["land_cover"]["legend_nesting"]["parent"]

        clr_ramp = _create_indexed_color_ramp("Land cover (7 class)")

        classes = legend_parent["key"]
        for c in classes:
            cls_name = c["name_long"]
            pix_val = c["code"]
            clr = QColor(c["color"])

            # Check if there is a matching ramp item so that we can use
            # the translated name for the category label.
            lbl_name = cls_name
            if pix_val in clr_ramp:
                item = clr_ramp[pix_val]
                lbl_name = item.label

            ramp_item = QgsColorRampShader.ColorRampItem(pix_val, clr, lbl_name)

            lc_mapping[cls_name] = ramp_item

        # Add no data
        nd = legend_parent["nodata"]
        nd_name = nd["name_long"]
        nd_color = QColor(nd["color"])
        nd_value = nd["code"]

        # Get translation
        nd_label = nd_name
        if nd_value in clr_ramp:
            item = clr_ramp[nd_value]
            nd_label = item.label

        nd_item = QgsColorRampShader.ColorRampItem(nd["code"], nd_color, nd_label)

        lc_mapping[nd_name] = nd_item

        return lc_mapping

    def summary_area(self) -> typing.List[UniqueValuesInfo]:
        """
        Detailed info about summary SDG 15.3.1 categories for plotting
        purposes.
        """
        temp_area_infos = []
        category_pix_value = self.summary_indicator_str_value_mapping()

        total_area = 0
        areas = self._baseline_results["sdg"]["summary"]["areas"]
        clr_ramp = _create_indexed_color_ramp("SDG 15.3.1 Indicator")

        # Create UniqueValuesInfo for each LDN summary category type.
        for category_info in areas:
            name = category_info["name"]
            area = category_info["area"]
            pix_val = category_pix_value[name]
            ramp_item = clr_ramp[pix_val]
            color = ramp_item.color

            # Darken stable color
            if pix_val == 0:
                color = QColor("#ffffca")

            vi = UniqueValuesInfo(area, ramp_item.label, pix_val, color, -1, -1)
            total_area += area
            temp_area_infos.append(vi)

        area_infos = []

        # Update with area percentage computed
        for tvi in temp_area_infos:
            area_percent = tvi.area / total_area * 100
            vi = UniqueValuesInfo(
                tvi.area,
                tvi.category_label,
                tvi.category_value,
                tvi.color,
                -1,
                area_percent,
            )
            area_infos.append(vi)

        return area_infos

    @classmethod
    def thematic_category_values_by_year(
        cls,
        values_root: typing.Dict,
        year: str,
        category_ramp_item_mapping: typing.Dict,
    ) -> typing.List[UniqueValuesInfo]:
        """
        Get value info collection for SDG 15.3.1 sub-indicators.
        """
        sdg_theme = values_root.get(str(year), None)

        if sdg_theme is None:
            return []

        theme_infos = []

        for lc_type, area in sdg_theme.items():
            # No need to include categories with zero area
            if area == 0:
                continue

            ramp_item = category_ramp_item_mapping[lc_type]

            vi = UniqueValuesInfo(
                area, ramp_item.label, ramp_item.value, ramp_item.color, -1, -1
            )
            theme_infos.append(vi)

        return theme_infos

    def land_cover(self, year: str) -> typing.List[UniqueValuesInfo]:
        """
        Detailed info about land cover for the given year.
        """
        lc_areas = self._baseline_results["land_cover"]["land_cover_areas_by_year"][
            "values"
        ]

        return self.thematic_category_values_by_year(
            lc_areas, year, self.land_cover_7_class_str_info_mapping()
        )

    def soc(self, year: str) -> typing.List[UniqueValuesInfo]:
        """
        Detailed info about soil organic carbon for the given year. SOC
        values are grouped by land cover hence we will use the land cover
        classes.
        """
        soc_areas = self._baseline_results["soil_organic_carbon"]["soc_stock_by_year"][
            "values"
        ]

        return self.thematic_category_values_by_year(
            soc_areas, year, self.land_cover_7_class_str_info_mapping()
        )

    @classmethod
    def value_info_change(
        cls,
        init_infos: typing.List[UniqueValuesInfo],
        final_infos: typing.List[UniqueValuesInfo],
    ) -> typing.List[UniqueValuesInfo]:
        """
        Computes difference between value infos in init and final years.
        """

        def compute_diff(
            init_info: UniqueValuesInfo, final_info: UniqueValuesInfo
        ) -> UniqueValuesInfo:
            area_diff = final_info.area - init_info.area
            area_percent = area_diff / init_info.area * 100

            return UniqueValuesInfo(
                area_diff,
                init_info.category_label,
                init_info.category_value,
                init_info.color,
                -1,
                area_percent,
            )

        return list(map(compute_diff, init_infos, final_infos))

    def lc_by_productivity(self) -> typing.Dict[str, typing.List[UniqueValuesInfo]]:
        """
        Land cover classes grouped by productivity.
        """
        prod_groups = self._baseline_results["productivity"][
            "crosstabs_by_productivity_class"
        ]

        category_item_mapping = self.land_cover_7_class_str_info_mapping()
        categories = list(category_item_mapping.keys())[:-1]  # Remove 'No data'

        lc_infos_by_prod_class = {}

        for pg in prod_groups:
            prod_name = pg["name"]
            values = pg["values"]
            prod_change = lc_productivity_change(values)

            # Create unique value infos for productivity class using
            # LC categories.
            prod_class_infos = []
            for i, c in enumerate(categories):
                area_diff, percent_diff = prod_change[i]
                ramp_item = category_item_mapping[c]

                # Remove dashes in category name
                lbls = ramp_item.label.split("-", maxsplit=1)
                label = lbls[0] if len(lbls) == 1 else lbls[1]

                lc_info = UniqueValuesInfo(
                    area_diff, label, ramp_item.value, ramp_item.color, -1, percent_diff
                )

                prod_class_infos.append(lc_info)

            lc_infos_by_prod_class[prod_name] = prod_class_infos

        return lc_infos_by_prod_class


def _create_indexed_color_ramp(
    style_name: str, band_info: typing.Dict = None
) -> typing.Dict[float, QgsColorRampShader.ColorRampItem]:
    # Create a dictionary containing color ramp items for categorical
    # items indexed by pixel value.
    band_style = styles.get(style_name, None)
    if band_style is None:
        return {}

    ramp_type = band_style["ramp"]["type"]
    if ramp_type == "categorical":
        clr_ramp = create_categorical_color_ramp(band_style["ramp"]["items"])
    elif ramp_type == "categorical from legend":
        clr_ramp = create_categorical_color_ramp_from_legend(
            band_info["metadata"]["nesting"]
        )
    elif ramp_type == "categorical transitions from legend":
        clr_ramp = create_categorical_transitions_color_ramp_from_legend(
            band_info["metadata"]["nesting"]
        )
    elif ramp_type == "categorical with dynamic ramp":
        clr_ramp = create_categorical_with_dynamic_ramp_color_ramp(
            band_style, band_info
        )
    else:
        return {}

    idx_clr_ramp = {int(cri.value): cri for cri in clr_ramp}

    return idx_clr_ramp


def lc_productivity_change(produc_lc_values: typing.List) -> typing.List[tuple]:
    """
    Create a 2D array containing area difference and percentage of
    productivity class.
    """
    value_lst = [vl["value"] for vl in produc_lc_values]
    val_array = np.array(value_lst)

    # Reshape to 7 by 7 for each LC class in initial and final years
    grouped_array = val_array.reshape((7, -1))

    initial_year_area_sum = np.sum(grouped_array, axis=0)
    final_year__area_sum = np.sum(grouped_array, axis=1)
    initial_year_total_area = np.sum(initial_year_area_sum)

    def compute_change(init_area, final_area):
        # Area change and its percentage.
        diff = final_area - init_area
        return diff, diff / initial_year_total_area * 100

    return list(map(compute_change, initial_year_area_sum, final_year__area_sum))
