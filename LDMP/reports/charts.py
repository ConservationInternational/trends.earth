"""Charts showing summary layer statistics."""

from collections import namedtuple
from dataclasses import field
from enum import Enum
import math
import os
import typing

import plotly.graph_objects as go

from qgis.PyQt.QtCore import (
    Qt,
    QTemporaryFile,
    QUrl
)
from qgis.PyQt.QtGui import (
    QColor
)

from qgis import processing
from qgis.core import (
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
    QgsVectorLayer
)

from ..jobs.models import Job
from ..layers import (
    create_categorical_color_ramp,
    styles
)
from .models import slugify


# Contains information about a layer and source band_info
LayerBandInfo = namedtuple(
    'LayerBandInfo',
    'layer band_info'
)


# Statistical information for a single classification category
UniqueValuesInfo = namedtuple(
    'UniqueValuesInfo',
    'area category_label category_value color count coverage_percent'
)


class BaseChart:
    """
    Abstract class for a statistical chart.
    """
    def __init__(self, **kwargs):
        self.layer_band_info = kwargs.pop('layer_band_info', None)
        self.root_output_dir = kwargs.pop('root_output_dir', '')
        self._paths = []
        self._dpi = 300
        self._measurement_converter = QgsLayoutMeasurementConverter()
        self._measurement_converter.setDpi(self._dpi)

        # Try to maintain 4:3 aspect ratio
        self._width_mm = 280
        self._height_mm = 210

    @classmethod
    def warning_msg(cls, msg: str) -> str:
        # Append class name to the message.
        cls_name = cls.__class__.__name__
        return f'{cls_name}: {msg}'

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
        return band_info['metadata']['year']

    def layer_name(self) -> str:
        """
        Returns the layer name that can be used when naming the output files.
        """
        layer = self.layer_band_info.layer
        if layer is None:
            return ''

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
        Converts length measure to equivalent pixels taking into account
        the resolution.
        """
        measurement = QgsLayoutMeasurement(
            length,
            QgsUnitTypes.LayoutMillimeters
        )
        pix_measurement = self._measurement_converter.convert(
            measurement,
            QgsUnitTypes.LayoutPixels
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
        frame.attemptMove(
            QgsLayoutPoint(8, 0, QgsUnitTypes.LayoutMillimeters)
        )
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
        html_path = f'{file_name}.html'

        # Write figure to html
        figure.write_html(
            html_path,
            auto_open=False,
            auto_play=False,
            config={'displayModeBar': False}
        )

        # Create and export layout
        layout = self._chart_layout(html_path)
        exporter = QgsLayoutExporter(layout)
        settings = QgsLayoutExporter.ImageExportSettings()
        res = exporter.exportToImage(path, settings)

        if res != QgsLayoutExporter.Success:
            return False

        return True


class BaseUniqueValuesChart(BaseChart):
    """
    Provides an interface for getting the statistics of each pixel value for
    a given band in a raster layer.
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.band_number = -1

    @classmethod
    def report(
            cls,
            layer_band_info: LayerBandInfo,
            band_number: int
    ) -> typing.List[UniqueValuesInfo]:
        """
        Returns a list containing area count for each unique pixel
        value for the given band.
        """
        layer = layer_band_info.layer
        band_info = layer_band_info.band_info
        band_info_name = band_info['name']
        band_style = styles.get(band_info_name, None)
        if band_style is None:
            return []

        # We will only support 'categorical' style since we are dealing
        # with absolute values.
        ramp_type = band_style["ramp"]["type"]
        if ramp_type != 'categorical':
            return []

        output_temp_file = QTemporaryFile()
        if not output_temp_file.open():
            return []

        if band_number < 1 or band_number > layer.bandCount():
            return []

        clr_ramp = create_categorical_color_ramp(band_style)
        idx_clr_ramp = {int(cri.value): cri for cri in clr_ramp}

        file_name = output_temp_file.fileName()

        alg_name = 'native:rasterlayeruniquevaluesreport'
        output_table = f'{file_name}.geojson'
        params = {
            'INPUT': layer,
            'BAND': band_number,
            'OUTPUT_TABLE': output_table
        }

        output = processing.run(alg_name, params)

        # Compute pixel size in sq km
        pixel_count = output['TOTAL_PIXEL_COUNT']
        area_calc = QgsDistanceArea()
        area_calc.setEllipsoid('WGS84')
        ext_geom = QgsGeometry.fromRect(layer.extent())
        extents_area = area_calc.measureArea(ext_geom)
        area_km = area_calc.convertAreaMeasurement(
            extents_area,
            QgsUnitTypes.AreaSquareKilometers
        )
        pixel_area = area_km / pixel_count

        unique_vals = []

        vl = QgsVectorLayer(output_table)
        feat_iter = vl.getFeatures()

        for f in feat_iter:
            pix_val = f['value']
            num_pixels = f['count']
            area_sq_km = num_pixels * pixel_area
            area_percent = area_sq_km / area_km * 100

            # Get label and color defined in the band style
            label = ''
            clr = Qt.lightGray
            int_pix_val = int(pix_val)
            if int_pix_val in idx_clr_ramp:
                ramp_item = idx_clr_ramp[int_pix_val]
                label = ramp_item.label
                clr = ramp_item.color

            vi = UniqueValuesInfo(
                area_sq_km,
                label,
                pix_val,
                clr,
                num_pixels,
                area_percent
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
            return False, ['Output directory not defined']

        if self.band_number < 1:
            return False, ['Band number cannot be less than one']

        lyr_name = self.layer_name()
        if not lyr_name:
            return False, ['Could not determine the layer name']

        vals_report = self.report(
            self.layer_band_info,
            self.band_number
        )
        output_file_path = f'{self.root_output_dir}/chart-{lyr_name}.png'

        labels = []
        values = []
        colors = []
        for val_info in vals_report:
            # Remove pixel value prefix
            lbls = val_info.category_label.split('-', maxsplit=1)
            label = lbls[0] if len(lbls) == 1 else lbls[1]

            labels.append(label)
            values.append(round(val_info.area))
            colors.append(val_info.color.name())

        year = self.year(self.layer_band_info.band_info)
        plot_title = f'Land Cover Area (km2) in {year!s}'

        pw, ph = self.preferred_size

        # Create and export pie chart
        fig = go.Figure(data=[go.Pie(labels=labels, values=values)])
        fig.update_traces(textinfo='value', marker=dict(colors=colors))
        fig.update_layout(title={
            'text': plot_title,
            'y':0.95,
            'x':0.5,
            'xanchor': 'center',
            'yanchor': 'top',
            'font':{'size': 25}
            },
            legend={
                'font':{'size': 13}
            },
            width=pw,
            height=ph
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
        self.target_layer_band_info = kwargs.pop('target_lbi', None)
        self.target_band_number = kwargs.pop('target_band', -1)
        self.chart_type = ChangeBarChartType.ALL
        super().__init__(**kwargs)

    def export(self) -> typing.Tuple[bool, list]:
        # Create clustered bar graph comparing initial and target years.
        if not self.root_output_dir:
            return False, ['Output directory not defined']

        if self.band_number < 1 or self.target_band_number < 1:
            return False, [
                'Initial and target band numbers must cannot be less than one'
            ]

        init_vals_report = self.report(
            self.layer_band_info,
            self.band_number
        )
        target_vals_report = self.report(
            self.target_layer_band_info,
            self.target_band_number
        )

        init_year = self.year(self.layer_band_info.band_info)
        target_year = self.year(self.target_layer_band_info.band_info)

        file_name = slugify(
            f'chart-land-cover-changes-{init_year!s}-{target_year!s}'
        )
        output_file_path = f'{self.root_output_dir}/{file_name}.png'

        labels = []
        init_values = []
        target_values = []
        init_colors = []
        target_colors = []
        for i in range(len(init_vals_report)):
            init_val_info = init_vals_report[i]
            target_val_info = target_vals_report[i]

            # Labels
            lbls = init_val_info.category_label.split('-', maxsplit=1)
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
        if self.chart_type == ChangeBarChartType.CLUSTERED or \
                self.chart_type == ChangeBarChartType.ALL:
            fig = go.Figure()
            # Init year
            fig.add_trace(
                go.Bar(
                    x=labels,
                    y=init_values,
                    name=str(init_year),
                    marker_color=init_colors,
                    text=init_values,
                    textposition='auto',
                    texttemplate='%{y:,.4r}',
                    textfont={
                        'size': 10
                    }
                )
            )
            # Target year
            fig.add_trace(
                go.Bar(
                    x=labels,
                    y=target_values,
                    name=str(target_year),
                    marker_color=target_colors,
                    text=target_values,
                    textposition='auto',
                    texttemplate='%{y:,.4r}',
                    textfont={
                        'size': 10
                    }
                )
            )

            plot_title = f'Land Cover Changes ({init_year!s}-{target_year!s})'

            fig.update_layout(title={
                'text': plot_title,
                'y': 0.95,
                'x': 0.5,
                'xanchor': 'center',
                'yanchor': 'top',
                'font': {'size': 25}
            },
                xaxis={
                    'tickfont_size':12
            },
                yaxis={
                    'title': 'Area (km2)',
                    'titlefont_size': 15,
                    'tickfont_size': 12,
                    'tickformat': ',.4r'
                },
                barmode='group',
                bargap=0.15,
                bargroupgap=0.1,
                showlegend=False,
                width=pw,
                height=ph
            )

            # Save image
            self.save_image(fig, output_file_path)
            self._paths.append(output_file_path)

        # Positive/negative bar graph
        if self.chart_type == ChangeBarChartType.POS_NEG or \
                self.chart_type == ChangeBarChartType.ALL:
            # Colors for positive or negative change
            pos_clr, neg_clr = QColor('#70D80F'), QColor('#FF5733')

            # Function for computing LULC change as percentage.
            # ia - init area, ta - target area
            lc_change_func = lambda ia, ta: (ta - ia) * 100 / ia
            lc_change_percent = list(
                map(lc_change_func, init_values, target_values)
            )

            # Set color based on value
            clr_range = [
                pos_clr.name() if c >= 0 else neg_clr.name()
                for c in lc_change_percent
            ]

            plot_title = f'Land Use Land Cover Changes in % ' \
                         f'({init_year!s}-{target_year!s})'

            # Set min/max values for the x range
            min_x = (math.ceil(min(lc_change_percent) / 10) * 10) - 25
            max_x = (math.ceil(max(lc_change_percent) / 10) * 10) + 20

            # Create and export figure
            fig = go.Figure()
            fig.add_trace(
                go.Bar(
                    y=labels,
                    x=lc_change_percent,
                    marker_color=clr_range,
                    text=lc_change_percent,
                    texttemplate='%{x:.2f}%',
                    textposition='outside',
                    textfont={
                        'size': 10
                    },
                    orientation='h'
                )
            )
            fig.update_layout(title={
                'text': plot_title,
                'y': 0.95,
                'x': 0.5,
                'xanchor': 'center',
                'yanchor': 'top',
                'font': {'size': 25}
            },
                yaxis={
                    'tickfont_size': 12
                },
                xaxis={
                    'tickfont_size': 12,
                    'ticksuffix': '%',
                    'range':[min_x, max_x]
                },
                showlegend=False,
                width=pw,
                height=ph
            )

            # Export
            file_name = slugify(
                f'chart-land-cover-changes-percent-{init_year!s}-'
                f'{target_year!s}'
            )
            output_file_path = f'{self.root_output_dir}/{file_name}.png'

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
        self._root_output_dir = kwargs.pop('root_output_dir', '')
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
            return False, ['Output directory not specified']

        if not os.path.exists(self._root_output_dir):
            return False, ['Output directory does not exist']

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
        fmt_msgs = map(lambda msg: f'{cls_name} - {msg}', messages)

        return status, fmt_msgs


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
            bi_name = bi['name']
            if bi_name == 'Land cover (7 class)':
                year = bi['metadata']['year']
                lc_layer_band_infos[year] = lbi

        sorted_lc_layer_band_infos = dict(sorted(lc_layer_band_infos.items()))
        sorted_band_infos = list(sorted_lc_layer_band_infos.values())
        init_layer_band_info = sorted_band_infos[0]
        target_layer_band_info = sorted_band_infos[1]

        init_band_num = 5
        target_band_num = 19

        init_yr_pie_chart = UniqueValuesPieChart(
            layer_band_info=init_layer_band_info,
            root_output_dir=self._root_output_dir
        )
        init_yr_pie_chart.band_number = init_band_num
        self._charts.append(init_yr_pie_chart)

        target_yr_pie_chart = UniqueValuesPieChart(
            layer_band_info=target_layer_band_info,
            root_output_dir=self._root_output_dir
        )
        target_yr_pie_chart.band_number = target_band_num
        self._charts.append(target_yr_pie_chart)

        # Add clustered bar graph
        lc_change_barchart = UniqueValuesChangeBarChart(
            layer_band_info=init_layer_band_info,
            target_lbi=target_layer_band_info,
            root_output_dir=self._root_output_dir
        )
        lc_change_barchart.band_number = init_band_num
        lc_change_barchart.target_band_number = target_band_num
        self._charts.append(lc_change_barchart)


class AlgorithmChartsManager:
    """
    Manages collection of algorithm configurations. Should be used as the
    main entry point when adding job layers and subsequently, generating
    charts.
    """
    def __init__(self, **kwargs):
        self._alg_charts_config_types = {}
        self._job_chart_configs = []
        self._root_output_dir = kwargs.pop('root_output_dir', '')
        self._set_default_chart_config_types()

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
        self.add_alg_chart_config('land-cover', LandCoverChartsConfiguration)

    def add_alg_chart_config(
            self,
            alg_name: str,
            chart_config: typing.Type[BaseAlgorithmChartsConfiguration]
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
            self,
            alg_name: str
    ) -> typing.Type[BaseAlgorithmChartsConfiguration]:
        """
        Returns the chart configuration class for the given algorithm, else None.
        """
        return self._alg_charts_config_types.get(alg_name, None)

    def add_job_layers(
            self,
            job: Job,
            band_infos: typing.List[LayerBandInfo]
    ) -> bool:
        """
        Add job-band_info mapping. If the algorithm for the job does not have
        a corresponding mapped chart configuration, it will return False.
        """
        alg_name = job.script.name

        chart_config_cls = self.alg_chart_config_by_name(alg_name)
        if chart_config_cls is None:
            return False

        chart_config_obj = chart_config_cls(
            job,
            band_infos,
            root_output_dir = self._root_output_dir
        )
        self._job_chart_configs.append(chart_config_obj)

        return True

    def get_chart_config_by_job(
            self,
            job: Job
    ) -> BaseAlgorithmChartsConfiguration:
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
        for jcc in self._job_chart_configs:
            res, msgs = jcc.generate()
            if not res:
                status = False

        return status

