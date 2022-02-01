# Modules for managing variables and expressions that can be used in a report.
from collections import namedtuple
import typing

from qgis.core import (
    QgsExpressionContextScope,
    QgsExpressionContextUtils,
    QgsLayout
)

from qgis.PyQt.QtCore import (
    QCoreApplication
)

from ..logger import log

# Most (if not) all of the variables' values will be set at runtime
JobAttrVarInfo = namedtuple(
    'JobAttrVarInfo',
    'job_attr var_name default_value'
)


def tr(message) -> str:
    return QCoreApplication.translate('report_expression', message)


def _job_attr_var_mapping() -> typing.List[JobAttrVarInfo]:
    # Job attribute and corresponding variable names.
    return [
        JobAttrVarInfo('id', 'te_job_id', ''),
        JobAttrVarInfo('script.name', 'te_job_alg_name', ''),
        JobAttrVarInfo('start_date', 'te_job_creation_date', ''),
        JobAttrVarInfo('status.value', 'te_job_status', ''),
        JobAttrVarInfo('task_name', 'te_job_name', '')
    ]


class ReportExpressionManager:
    """
    Helper functions for expressions and variables used in a report.
    """
    @staticmethod
    def register_variables(layout: QgsLayout):
        # Registers job-related variables in the layout scope.
        layout_scope = QgsExpressionContextUtils.layoutScope(layout)
        for jv_info in _job_attr_var_mapping():
            QgsExpressionContextUtils.setLayoutVariable(
                layout,
                jv_info.var_name,
                jv_info.default_value
            )