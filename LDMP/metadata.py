import os
import tempfile
from pathlib import Path

import lxml.etree as ET
import qgis.core
from qgis.PyQt import QtCore
from qgis.PyQt import QtXml

from .jobs import manager
from .jobs.models import Job
from .logger import log


XSL_PATH = os.path.join(os.path.dirname(__file__), "data", "xsl")


def save_qmd(file_path, metadata):
    dom_impl = QtXml.QDomImplementation()
    doc_type = dom_impl.createDocumentType("qgis", "http://mrcc.com/qgis.dtd", "SYSTEM")
    document = QtXml.QDomDocument(doc_type)

    root_node = document.createElement("qgis")
    root_node.setAttribute("version", qgis.core.Qgis.version())
    document.appendChild(root_node)

    if not metadata.writeMetadataXml(root_node, document):
        log("Could not save metadata")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(document.toString(2))


def read_qmd(file_path):
    md = qgis.core.QgsLayerMetadata()
    if not os.path.exists(file_path):
        return md

    document = QtXml.QDomDocument("qgis")
    with open(file_path, "r", encoding="utf-8") as f:
        if not document.setContent(f.read()):
            log("Could not read metadata from file {}".format(md_path))
            return md

    root = document.firstChildElement("qgis")
    if root.isNull():
        log("Root <qgis> element could not be found")
        return md

    md.readMetadataXml(root)
    return md


def qmd_to_iso(qmd_path):
    file_name = os.path.splitext(os.path.split(qmd_path)[1])[0] + ".xml"
    temp_file = os.path.join(tempfile.gettempdir(), file_name)

    in_dom = ET.parse(qmd_path)
    print(
        os.path.join(XSL_PATH, "qgis-to-iso19139.xsl"),
        os.path.exists(os.path.join(XSL_PATH, "qgis-to-iso19139.xsl")),
    )
    xslt = ET.parse(os.path.join(XSL_PATH, "qgis-to-iso19139.xsl"))
    transform = ET.XSLT(xslt)
    out_dom = transform(in_dom)

    s = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + ET.tostring(out_dom, pretty_print=True).decode()
    )
    with open(temp_file, "w", encoding="utf8") as f:
        f.write(s)

    return Path(temp_file)


def init_dataset_metadata(job: Job, metadata: qgis.core.QgsLayerMetadata = None):
    md = read_dataset_metadata(job)
    if metadata is None:
        md.setTitle(job.task_name)
        md.setAbstract(job.task_notes)
    else:
        md.combine(metadata)

    file_path = os.path.splitext(manager.job_manager.get_job_file_path(job))[0] + ".qmd"
    save_qmd(file_path, md)

    for u in job.results.get_all_uris():
        init_layer_metadata(u.uri, md)


def init_layer_metadata(uri, metadata):
    md = None
    if metadata is None:
        md = qgis.core.QgsLayerMetadata()
    else:
        md = metadata.clone()

    layer = qgis.core.QgsRasterLayer(str(uri), "tmp", "gdal")

    md.setCrs(layer.dataProvider().crs())
    spatialExtent = qgis.core.QgsLayerMetadata.SpatialExtent()
    spatialExtent.bounds = qgis.core.QgsBox3d(layer.extent())
    spatialExtent.extentCrs = layer.dataProvider().crs()
    spatialExtents = [spatialExtent]
    extent = qgis.core.QgsLayerMetadata.Extent()
    extent.setSpatialExtents(spatialExtents)
    md.setExtent(extent)

    file_path = os.path.splitext(uri)[0] + ".qmd"
    save_qmd(file_path, md)


def update_dataset_metadata(
    job: Job, metadata: qgis.core.QgsLayerMetadata, updateLayers: bool = False
):
    file_path = os.path.splitext(manager.job_manager.get_job_file_path(job))[0] + ".qmd"
    save_qmd(file_path, metadata)

    if updateLayers:
        for u in job.results.get_all_uris():
            update_layer_metadata(u.uri, metadata)


def update_layer_metadata(uri, metadata):
    layer = qgis.core.QgsRasterLayer(str(uri), "tmp", "gdal")
    md = layer.metadata()

    if md == metadata:
        return

    md = combine_metadata(md, metadata)

    file_path = os.path.splitext(uri)[0] + ".qmd"
    save_qmd(file_path, md)


def combine_metadata(metadata, other):
    if other.identifier() != "":
        metadata.setIdentifier(other.identifier())

    if other.parentIdentifier() != "":
        metadata.setarentIdentifier(other.parentIdentifier())

    if other.language() != "":
        metadata.setLanguage(other.language())

    if other.type() != "":
        metadata.setType(other.type())

    if other.title() != "":
        metadata.setTitle(other.title())

    if other.abstract() != "":
        metadata.setAbstract(other.abstract())

    if other.history() != "":
        metadata.setHistory(other.history())

    if len(other.keywords()) > 0:
        metadata.setKeywords(other.keywords())

    if len(other.contacts()) > 0:
        metadata.setContacts(other.contacts())

    if len(other.links()) > 0:
        metadata.setLinks(other.links())

    if other.fees() != "":
        metadata.setFees(other.fees())

    if len(other.constraints()) > 0:
        metadata.setConstraints(other.constraints())

    if len(other.rights()) > 0:
        metadata.setRights(other.rights())

    if len(other.licenses()) > 0:
        metadata.setLicenses(other.licenses())

    if other.encoding() != "":
        metadata.setEncoding(other.encoding())

    if other.crs().isValid():
        metadata.setCrs(other.crs())

    if len(other.extent().spatialExtents()) > 0:
        extent = metadata.extent()
        extent.setSpatialExtents(other.extent().spatialExtents())
        metadata.setExtent(extent)

    if len(other.extent().temporalExtents()) > 0:
        extent = metadata.extent()
        extent.setTemporalExtents(other.extent().temporalExtents())
        metadata.setExtent(extent)


def export_dataset_metadata(job: Job):
    md_paths = list()

    file_path = manager.job_manager.get_job_file_path(job)
    md_path = os.path.splitext(file_path)[0] + ".qmd"
    if not os.path.exists(md_path):
        log("Could not find dataset metadata file {}".format(md_path))
    else:
        md_paths.append(qmd_to_iso(md_path))

    for u in job.results.get_all_uris():
        file_path = u.uri
        md_path = os.path.splitext(file_path)[0] + ".qmd"
        if not os.path.exists(md_path):
            log("Could not find dataset metadata file {}".format(md_path))
        else:
            md_paths.append(qmd_to_iso(md_path))

    return md_paths


def read_dataset_metadata(job: Job):
    file_path = manager.job_manager.get_job_file_path(job)
    md_path = os.path.splitext(file_path)[0] + ".qmd"
    return read_qmd(md_path)
