"""PDF of the ecosystem restoration progress report, from a QGIS print layout
template (.qpt)."""

from pathlib import Path

from qgis.core import (
    QgsExpressionContextUtils,
    QgsLayoutExporter,
    QgsLayoutItemPicture,
    QgsPrintLayout,
    QgsProject,
    QgsReadWriteContext,
)
from qgis.PyQt.QtXml import QDomDocument

from ....logger import log

try:
    _EXPORT_SUCCESS = QgsLayoutExporter.Success
except AttributeError:
    _EXPORT_SUCCESS = QgsLayoutExporter.ExportResult.Success


def write_pdf(
    template_path: Path,
    variables: dict[str, str],
    pictures: dict[str, Path],
    pdf_path: Path,
) -> Path | None:
    """
    Export the template as PDF.

    variables are set as layout variables, used in the labels of the template
    as [% @name %]. pictures maps the id of a picture item to its image, the
    picture items without an image are hidden.
    Returns the path of the PDF, or None when it could not be exported.
    """
    document = QDomDocument()
    if not document.setContent(template_path.read_text(encoding="utf-8")):
        log(f"Could not read the report template {template_path}")
        return None

    # The layout belongs to a project of its own, not to the opened project
    project = QgsProject()
    layout = QgsPrintLayout(project)
    _, loaded = layout.loadFromTemplate(document, QgsReadWriteContext())
    if not loaded:
        log(f"Could not load the report template {template_path}")
        return None

    for name, value in variables.items():
        QgsExpressionContextUtils.setLayoutVariable(layout, name, value)

    for item in layout.items():
        if not isinstance(item, QgsLayoutItemPicture):
            continue
        image_path = pictures.get(item.id())
        if image_path is not None and image_path.exists():
            item.setPicturePath(str(image_path))
        else:
            item.setVisibility(False)

    result = QgsLayoutExporter(layout).exportToPdf(
        str(pdf_path), QgsLayoutExporter.PdfExportSettings()
    )
    if result != _EXPORT_SUCCESS:
        log(f"Could not export the report PDF {pdf_path.name}: {result}")
        return None

    return pdf_path
