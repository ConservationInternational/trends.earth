# Module for managing variables and expressions that can be used in a report.

from collections import namedtuple
import json
from operator import attrgetter
import typing

from qgis.core import QgsExpressionContext, QgsLayout, QgsRasterLayer

from qgis.PyQt.QtCore import QCoreApplication

from ..conf import Setting, settings_manager
from ..jobs.models import Job
from ..utils import utc_to_local

# Most (if not) all of the job variables' values will be set at runtime
JobAttrVarInfo = namedtuple(
    "JobAttrVarInfo", "job_attr var_name default_value fmt_func"
)


# Values extracted from the report settings
ReportSettingVarInfo = namedtuple(
    "ReportSettingVarInfo", "setting var_name default_value"
)


# Information about the current job layer being processed
LayerVarInfo = namedtuple("LayerVarInfo", "var_name default_value fmt_func")


def tr(message) -> str:
    return QCoreApplication.translate("report_expression", message)


def format_json(obj) -> str:
    """
    Formats a dictionary for presentation as a JSON object in a
    report variable.
    """
    return json.dumps(obj, indent=4, sort_keys=True)


def format_creation_date(creation_date) -> str:
    """
    Format job start date for presentation in a date report variable.
    """
    return str(utc_to_local(creation_date).strftime("%Y-%m-%d %H:%M"))


def _job_attr_var_mapping() -> typing.List[JobAttrVarInfo]:
    # Job attribute and corresponding variable names.
    return [
        JobAttrVarInfo("id", "te_job_id", "", str),
        JobAttrVarInfo("params", "te_job_input_params", {}, format_json),
        JobAttrVarInfo("results.uri.uri", "te_job_paths", "", str),
        JobAttrVarInfo("script.name", "te_job_alg_name", "", None),
        JobAttrVarInfo("start_date", "te_job_creation_date", "", format_creation_date),
        JobAttrVarInfo("status.value", "te_job_status", "", None),
        JobAttrVarInfo("task_name", "te_job_name", "", None),
        JobAttrVarInfo("task_notes", "te_job_comments", "", None),
    ]


def _report_settings_var_mapping() -> typing.List[ReportSettingVarInfo]:
    # Report setting variables with the corresponding values.
    org_logo_path = settings_manager.get_value(Setting.REPORT_ORG_LOGO_PATH)
    org_name = settings_manager.get_value(Setting.REPORT_ORG_NAME)
    footer = settings_manager.get_value(Setting.REPORT_FOOTER)
    disclaimer = settings_manager.get_value(Setting.REPORT_DISCLAIMER)

    return [
        ReportSettingVarInfo(
            Setting.REPORT_ORG_LOGO_PATH, "te_report_organization_logo", org_logo_path
        ),
        ReportSettingVarInfo(
            Setting.REPORT_ORG_NAME, "te_report_organization_name", org_name
        ),
        ReportSettingVarInfo(Setting.REPORT_FOOTER, "te_report_footer", footer),
        ReportSettingVarInfo(
            Setting.REPORT_DISCLAIMER, "te_report_disclaimer", disclaimer
        ),
    ]


def _current_job_layer_var_mapping() -> typing.List[LayerVarInfo]:
    # Current job map layer variables whose values will be set at runtime.
    return [LayerVarInfo("te_current_layer_name", "", lambda layer: layer.name())]


def _get_var_names(var_info_collection: typing.List) -> typing.List[str]:
    # Returns the variable names from the info objects
    return [vi.var_name for vi in var_info_collection]


class ReportExpressionUtils:
    """
    Helper functions for expressions and variables used in a report.
    """

    VAR_NAMES_PROP = "variableNames"
    VAR_VALUES_PROP = "variableValues"

    @staticmethod
    def register_variables(layout: QgsLayout) -> None:
        """
        Registers both job-related and report setting variables in the layout
        scope.
        """
        ReportExpressionUtils.register_job_variables(layout)
        ReportExpressionUtils.register_report_settings_variables(layout)
        ReportExpressionUtils.register_current_job_layer_settings_variables(layout)

        # Need to re-evaluate expressions for layout picture items.
        layout.refresh()

    @staticmethod
    def register_job_variables(layout: QgsLayout):
        # Registers job-related variable names since the values will be set
        # at runtime.
        ReportExpressionUtils._register_variable_collection(
            layout, _job_attr_var_mapping()
        )

    @staticmethod
    def register_report_settings_variables(layout: QgsLayout):
        # Register/update report variables based on the values in the settings.
        ReportExpressionUtils._register_variable_collection(
            layout, _report_settings_var_mapping()
        )

    @staticmethod
    def register_current_job_layer_settings_variables(layout: QgsLayout):
        # Register variables for the current job layer when the report is
        # running.
        ReportExpressionUtils._register_variable_collection(
            layout, _current_job_layer_var_mapping()
        )

    @staticmethod
    def _register_variable_collection(
        layout: QgsLayout, var_info_collection: typing.List
    ):
        var_names = _get_var_names(var_info_collection)

        # Remove duplicate names and corresponding values
        var_names, var_values = ReportExpressionUtils.remove_variables(
            layout, var_names
        )

        # Now append our variable names with corresponding values
        for var_info in var_info_collection:
            var_names.append(var_info.var_name)
            var_values.append(var_info.default_value)

        layout.setCustomProperty(ReportExpressionUtils.VAR_NAMES_PROP, var_names)
        layout.setCustomProperty(ReportExpressionUtils.VAR_VALUES_PROP, var_values)

    @staticmethod
    def remove_variables(
        layout: QgsLayout, rem_var_names: typing.List[str]
    ) -> typing.Tuple[typing.List, typing.List]:
        """
        Removes variables from the layout before adding new ones to ensure
        there are no duplicates.
        """
        var_names = layout.customProperty(ReportExpressionUtils.VAR_NAMES_PROP, [])
        var_values = layout.customProperty(ReportExpressionUtils.VAR_VALUES_PROP, [])
        for rvn in rem_var_names:
            ReportExpressionUtils.remove_variable_name_value(rvn, var_names, var_values)

        return var_names, var_values

    @staticmethod
    def remove_variable_name_value(
        rem_var_name: str, var_names: typing.List[str], var_values: typing.List[str]
    ):
        # Remove the variable name and corresponding value from the collection.
        while rem_var_name in var_names:
            idx = var_names.index(rem_var_name)
            _ = var_names.pop(idx)
            _ = var_values.pop(idx)

    @staticmethod
    def update_job_layer_expression_context(
        ctx: QgsExpressionContext, layer: QgsRasterLayer
    ) -> QgsExpressionContext:
        # Update expression context with values from current job layer.
        for layer_info in _current_job_layer_var_mapping():
            if not ctx.hasVariable(layer_info.var_name):
                continue
            active_scope = ctx.activeScopeForVariable(layer_info.var_name)

            try:
                fmt_func = layer_info.fmt_func
                if fmt_func is None:
                    continue
                layer_var_value = fmt_func(layer)
                active_scope.setVariable(layer_info.var_name, layer_var_value)
            except AttributeError:
                continue

        return ctx

    @staticmethod
    def update_job_expression_context(
        ctx: QgsExpressionContext, job: Job
    ) -> QgsExpressionContext:
        # Update expression context with job attribute values.
        for jv_info in _job_attr_var_mapping():
            if not ctx.hasVariable(jv_info.var_name):
                continue
            active_scope = ctx.activeScopeForVariable(jv_info.var_name)

            # Ensure the given job attribute exists
            try:
                getattr_func = attrgetter(jv_info.job_attr)
                job_attr_value = getattr_func(job)

                # Format value if required especially those ones that the
                # QgsExpression cannot convert or does not provide a function
                # for representing the value.
                fmt_func = jv_info.fmt_func
                if fmt_func is not None:
                    job_attr_value = fmt_func(job_attr_value)

                active_scope.setVariable(jv_info.var_name, job_attr_value)
            except AttributeError:
                continue

        return ctx

    @staticmethod
    def update_expression_context(
        ctx: QgsExpressionContext, job: Job, layer: QgsRasterLayer
    ):
        # Update expression contexts for current job and job layer in the
        # report generation cycle.
        ctx = ReportExpressionUtils.update_job_expression_context(ctx, job)
        ctx = ReportExpressionUtils.update_job_layer_expression_context(ctx, layer)

        return ctx
