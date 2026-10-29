"""PDF of the ecosystem restoration progress report charts."""

from pathlib import Path

from qgis.PyQt.QtCore import QMarginsF, QRectF
from qgis.PyQt.QtGui import QImage, QPageLayout, QPageSize, QPainter, QPdfWriter

from ....logger import log

PDF_FULL_WIDTH_PX = 900


def _enum(cls, scope: str, name: str):
    """Qt enum value for both Qt5 (cls.name) and Qt6 (cls.scope.name)."""
    value = getattr(cls, name, None)
    if value is not None:
        return value
    return getattr(getattr(cls, scope), name)


def write_pdf(image_paths: list[Path], pdf_path: Path) -> Path:
    """Write the images one below the other on A4 pages."""
    writer = QPdfWriter(str(pdf_path))
    writer.setPageSize(QPageSize(_enum(QPageSize, "PageSizeId", "A4")))
    writer.setPageMargins(
        QMarginsF(15, 15, 15, 15), _enum(QPageLayout, "Unit", "Millimeter")
    )
    writer.setResolution(150)

    painter = QPainter(writer)
    try:
        page_width = writer.width()
        page_height = writer.height()
        spacing = page_height * 0.02
        y = 0.0
        for image_path in image_paths:
            image = QImage(str(image_path))
            if image.isNull():
                log(f"Image {image_path.name} could not be added to the PDF")
                continue

            # Keep the relative size of the charts, a full width chart fills
            # the page width
            width = min(page_width, page_width * image.width() / PDF_FULL_WIDTH_PX)
            height = image.height() * width / image.width()
            if height > page_height:
                width *= page_height / height
                height = page_height
            if y > 0 and y + height > page_height:
                writer.newPage()
                y = 0.0

            painter.drawImage(QRectF((page_width - width) / 2, y, width, height), image)
            y += height + spacing
    finally:
        painter.end()

    return pdf_path
