# Modules for managing variables and expressions that can be used in a report.
from collections import namedtuple
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
from ..logger import log
from ..utils import (
    deep_get_attr,
    deep_has_attr
)

# Most (if not) all of the variables' values will be set at runtime
JobAttrVarInfo = namedtuple(
    'JobAttrVarInfo',
    'job_attr var_name default_value var_description'
)


def tr(message) -> str:
    return QCoreApplication.translate('report_expression', message)


def _job_attr_var_mapping() -> typing.List[JobAttrVarInfo]:
    # Job attribute and corresponding variable names.
    return [
        JobAttrVarInfo(
            'id', 'te_job_id', '', tr('The unique identifier for a job')
        ),
        JobAttrVarInfo(
            'params', 'te_job_input_params', '', tr('Input parameters in JSON')
        ),
        JobAttrVarInfo(
            'results.uri.uri', 'te_job_paths', '', tr('Path to the output files')
        ),
        JobAttrVarInfo(
            'script.name', 'te_job_alg_name', '', tr('Name of script used for the job')
        ),
        JobAttrVarInfo(
            'start_date', 'te_job_creation_date', '', tr('Job creation date')
        ),
        JobAttrVarInfo(
            'status.value', 'te_job_status', '', tr('Status of the job')
        ),
        JobAttrVarInfo(
            'task_name', 'te_job_name', '', tr('Job name as specified by the user')
        ),
        JobAttrVarInfo(
            'task_notes', 'te_job_comments', '', tr('User comments')
        )
    ]


class ReportExpressionUtils:
    """
    Helper functions for expressions and variables used in a report.
    """
    @staticmethod
    def register_variables(layout: QgsLayout):
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
        # Update expression context with job details
        for jv_info in _job_attr_var_mapping():
            if not ctx.hasVariable(jv_info.var_name):
                continue
            active_scope = ctx.activeScopeForVariable(
                jv_info.var_name
            )
            if deep_has_attr(job, jv_info.job_attr):
                job_attr_value = deep_get_attr(job, jv_info.job_attr)
                active_scope.setVariable(jv_info.var_name, job_attr_value)

        return ctx