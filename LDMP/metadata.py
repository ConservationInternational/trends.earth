import os
import tempfile
from pathlib import Path

import qgis.core
from qgis.PyQt import QtCore
from qgis.PyQt import QtXml

import lxml.etree as ET

from .jobs import manager
from .jobs.models import Job
from .logger import log
from . import layers
from te_schemas.results import Band as JobBand


XSL_PATH = os.path.join(os.path.dirname(__file__), 'data', 'xsl')


def save_qmd(file_path, metadata):
    dom_impl = QtXml.QDomImplementation()
    doc_type = dom_impl.createDocumentType('qgis', 'http://mrcc.com/qgis.dtd', 'SYSTEM')
    document = QtXml.QDomDocument(doc_type)

    root_node = document.createElement('qgis')
    root_node.setAttribute('version', qgis.core.Qgis.version())
    document.appendChild(root_node)

    if not metadata.writeMetadataXml(root_node, document):
        log(u'Could not save metadata')

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(document.toString(2))


def read_qmd(file_path):
    md = qgis.core.QgsLayerMetadata()
    if not os.path.exists(file_path):
        return md

    document = QtXml.QDomDocument('qgis')
    with open(file_path, 'r', encoding='utf-8') as f:
       if not document.setContent(f.read()):
           log(u'Could not read metadata from file {}'.format(md_path))
           return md

    root = document.firstChildElement('qgis')
    if root.isNull():
        log(u'Root <qgis> element could not be found')
        return md

    md.readMetadataXml(root)
    return md


def qmd_to_iso(qmd_path):
    file_name = os.path.splitext(os.path.split(qmd_path)[1])[0] + '.xml'
    temp_file = os.path.join(tempfile.gettempdir(), file_name)

    in_dom = ET.parse(qmd_path)
    print(os.path.join(XSL_PATH, 'qgis-to-iso19139.xsl'), os.path.exists(os.path.join(XSL_PATH, 'qgis-to-iso19139.xsl')))
    xslt = ET.parse(os.path.join(XSL_PATH, 'qgis-to-iso19139.xsl'))
    transform = ET.XSLT(xslt)
    out_dom = transform(in_dom)

    s = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(out_dom, pretty_print=True).decode()
    with open(temp_file, 'w', encoding='utf8') as f:
        f.write(s)

    return Path(temp_file)


def export_dataset_metadata(job: Job):
    md_paths = list()

    file_path = os.path.splitext(manager.job_manager.get_job_file_path(job))[0] + '.qmd'
    if not os.path.exists(file_path):
        log(u'Could not find dataset metadata file {}'.format(file_path))
    else:
        md_paths.append(qmd_to_iso(file_path))

    if job.results.uri.uri.suffix in [".tif", ".vrt"]:
        for n, band in enumerate(job.results.get_bands()):
            t = f'Band {n}: {layers.get_band_title(JobBand.Schema().dump(band))}'
            fp = os.path.splitext(file_path)[0] + '_{}.qmd'.format(n)
            if not os.path.exists(fp):
                log(u'Could not find band metadata file {}'.format(fp))
            else:
                md_paths.append(qmd_to_iso(fp))

    return md_paths
