# Modules for managing variables and expressions that can be used in a report.
from collections import namedtuple
from datetime import datetime
import json
import typing

from qgis.core import (
    QgsExpressionContext,
    QgsExpressionContextScope,
    QgsExpressionContextUtils,
    QgsLayout
)

from qgis.PyQt.QtCore import (
    QCoreApplication
)

from ..jobs.models import Job
from ..utils import (
    deep_get_attr,
    deep_has_attr,
    utc_to_local
)

# Most (if not) all of the variables' values will be set at runtime
JobAttrVarInfo = namedtuple(
    'JobAttrVarInfo',
    'job_attr var_name default_value fmt_func'
)


def tr(message) -> str:
    return QCoreApplication.translate('report_expression', message)


def format_json(obj) -> str:
    """
    Formats a dictionary for presentation as a JSON object in a
    report variable.
    """
    return json.dumps(obj, indent=4, sort_keys=True)


def format_creation_date(creation_date) -> str:
    """
    Format job start date.
    """
    return str(utc_to_local(creation_date).strftime("%Y-%m-%d %H:%M"))


def _job_attr_var_mapping() -> typing.List[JobAttrVarInfo]:
    # Job attribute and corresponding variable names.
    return [
        JobAttrVarInfo('id', 'te_job_id', '', str),
        JobAttrVarInfo('params', 'te_job_input_params', {}, format_json),
        JobAttrVarInfo('results.uri.uri', 'te_job_paths', '', str),
        JobAttrVarInfo('script.name', 'te_job_alg_name', '', None),
        JobAttrVarInfo(
            'start_date', 'te_job_creation_date', '', format_creation_date
        ),
        JobAttrVarInfo('status.value', 'te_job_status', '', None),
        JobAttrVarInfo('task_name', 'te_job_name', '', None),
        JobAttrVarInfo('task_notes', 'te_job_comments', '', None)
    ]


class ReportExpressionUtils:
    """
    Helper functions for expressions and variables used in a report.
    """
    @staticmethod
    def register_variables(layout: QgsLayout) -> None:
        # Registers job-related variables in the layout scope.
        for jv_info in _job_attr_var_mapping():
            QgsExpressionContextUtils.setLayoutVariable(
                layout,
                jv_info.var_name,
                jv_info.default_value
            )

    @staticmethod
    def update_expression_context(
            ctx: QgsExpressionContext,
            job: Job
    ) -> QgsExpressionContext:
        # Update expression context with job attribute values.
        for jv_info in _job_attr_var_mapping():
            if not ctx.hasVariable(jv_info.var_name):
                continue
            active_scope = ctx.activeScopeForVariable(
                jv_info.var_name
            )
            if deep_has_attr(job, jv_info.job_attr):
                job_attr_value = deep_get_attr(job, jv_info.job_attr)

                # Format value if required especially those ones that the
                # QgsExpression cannot convert or does not provide a function
                # for representing the value.
                fmt_func = jv_info.fmt_func
                if fmt_func is not None:
                    job_attr_value = fmt_func(job_attr_value)

                active_scope.setVariable(jv_info.var_name, job_attr_value)

        return ctx