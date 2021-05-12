"""
/***************************************************************************
 LDMP - A QGIS plugin
 This plugin supports monitoring and reporting of land degradation to the UNCCD 
 and in support of the SDG Land Degradation Neutrality (LDN) target.
                              -------------------
        begin                : 2021-03-23
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Conservation International
        email                : trends.earth@conservation.org
 ***************************************************************************/
"""

__author__ = 'Luigi Pirelli / Kartoza'
__date__ = '2021-03-23'

from typing import Optional, Union, List, Dict
from datetime import datetime
from enum import Enum
import abc
import os
import json
from collections import OrderedDict

from qgis.PyQt.QtCore import QSettings, pyqtSignal, QObject
from qgis.core import QgsLogger
from LDMP.jobs import Job, JobSchema
from LDMP.calculate import get_script_group
from LDMP import log, singleton, tr, json_serial

import marshmallow
from marshmallow import fields, Schema
from LDMP.schemas.schemas import APIResponseSchema


class DatasetStatus(Enum):
    """TODO: remove because simplified using the same Job status."""
    available = 0,
    being_generated = 1,
    downloading = 2,
    unavailable = 3,
    not_applicable = 4


DatasetStatusStrings = [e.name for e in DatasetStatus]


def getStatusEnum(status: str) -> DatasetStatus:
    """TODO: remove as commented above"""
    # get APIResponseSchema and remap into DatasetStatus
    ds_status = DatasetStatus.not_applicable
    if status in ['PENDING']:
        ds_status = DatasetStatus.being_generated
    elif status in ['SUCCESS', 'FINISHED']:
        ds_status = DatasetStatus.available
    else:
        ds_status = DatasetStatus.not_applicable

    return ds_status


# TODO: remove
# class DatasetSource(object):
#     def __init__(self):
#         super().__init__()

class FinalMeta(type(abc.ABC), type(QObject)):
    """trick to allow multiple hineritance. Need to allow also QObject
    hineritance to allow emitting pyqtSingla."""
    pass


class DatasetBase(abc.ABC, QObject, metaclass=FinalMeta):
    """implemented a base class in case need to expand the three with new nodes."""

    def __init__(self) -> None:
        super().__init__()

    def row(self) -> int:
        return 0

    @abc.abstractmethod
    def rowCount(self) -> int:
        pass

    @abc.abstractmethod
    def columnCount(self) -> int:
        pass

    @abc.abstractmethod
    def child(self, row) -> None:
        pass


class Dataset(DatasetBase):
    dumped = pyqtSignal(str)

    def __init__(self,
                 job: Optional[Job] = None,
                 dataset: Optional[Dict] = None
                 ) -> None:
        super().__init__()

        if job:
            job_schema = JobSchema()
            self.job = job_schema.dump(job)

            self.status: str = job.status
            # self.status: DatasetStatus = getStatusEnum(job.status)
            self.progress = job.progress
            self.source = job.scriptName
            self.name = job.taskName
            self.creation_date = job.startDate
            self.run_id = job.runId
        elif dataset:
            self.job = ''

            self.status = dataset.get('status')
            # self.status: DatasetStatus = getStatusEnum(job.status)
            self.progress = dataset.get('progress')
            self.source = dataset.get('source')
            self.name = dataset.get('name')
            self.creation_date = dataset.get('creation_date')
            self.run_id = dataset.get('run_id')
        else:
            raise Exception('Nor input Job or dataset dictionary are set to build a Dataset instance')

    def columnCount(self) -> int:
        return 1

    def rowCount(self) -> int:
        return 0

    def child(self, row: int) -> None:
        return None

    def columnName(self, column: int) -> Union[str, None]:
        return None

    def dump(self) -> str:
        """Dump Dataset as JSON in a programmatically set folder with a programmatically set filename.
        """
        # create path and filename where to dump Job descriptor
        out_path = ''
        base_data_directory = QSettings().value("trends_earth/advanced/base_data_directory", None, type=str)

        # TODO: set subfolder basing on the nature of Dataset
        # for now only 'outputs'
        out_path = os.path.join(base_data_directory, 'outputs')

        # set location where to save basing on script(alg) used
        script_name = self.source
        components = script_name.split()
        components = components[:-1] if len(components) > 1 else components  # eventually remove version that return
        # when getting executions list
        formatted_script_name = '-'.join(components)  # remove al version and substitutes ' ' with '-'
        formatted_script_name = formatted_script_name.lower()

        # get alg group to setup subfolder
        group = get_script_group(formatted_script_name)
        if not group:
            log(tr('Cannot get group of the script: ') + formatted_script_name)
            group = 'UNKNOW_GROUP_FOR_' + formatted_script_name

        # get execution date as subfolder name
        processing_date_string = self.creation_date
        if isinstance(processing_date_string, datetime):
            processing_date_string = self.creation_date.strftime('%Y_%m_%d')

        out_path = os.path.join(out_path, group, processing_date_string)
        if not os.path.exists(out_path):
            os.makedirs(out_path)

        descriptor_file_name = self.run_id + '.json'
        descriptor_file_name = os.path.join(out_path, descriptor_file_name)
        QgsLogger.debug('* Dump dataset descriptor into file: ' + descriptor_file_name, debuglevel=4)

        schema = DatasetSchema()
        with open(descriptor_file_name, 'w') as f:
            json.dump(
                schema.dump(self),
                f, default=json_serial, sort_keys=True, indent=4, separators=(',', ': ')
            )
        self.dumped.emit(descriptor_file_name)
        return descriptor_file_name


@singleton
class Datasets(QObject):
    """Singleton container to separate Dialog to Job operations as retrieve and update.
    
    It shouldn't be necessary in case of using QListView, but using TreeView to allow
    more flexibility.
    """
    datasetsStore: Dict[str, Dataset] = OrderedDict()
    updated = pyqtSignal()

    def __init__(self):
        super().__init__()

    def reset(self, emit: bool = False):
        """Remove any Dataset and related json counterpart."""
        # remove any json of the available Jobs in self.jobs
        # for file_name in self.datasetsStore.keys():
        #     os.remove(file_name)
        self.datasetsStore = OrderedDict()
        if emit:
            self.updated.emit()

    def set(self, datasets_dict: Optional[List[dict]] = None):
        # remove previous jobs
        self.reset()

        if datasets_dict is None:
            return

        # set new ones
        for dataset_dict in datasets_dict:
            self.append(dataset_dict)
        self.updated.emit()

    def appendFromJob(self, job: Job) -> (str, Dataset):
        """Create a Dataset and dump basing an assumed valid Job."""
        dataset = Dataset(job=job)
        dump_file_name = dataset.dump()  # doing save in default location

        # add in memory store .e.g a dictionary
        self.datasetsStore[dump_file_name] = dataset

        return (dump_file_name, dataset)

    # method useful to interface with MVC model
    def columnCount(self) -> int:
        return 1

    def rowCount(self) -> int:
        return len(self.datasetsStore)

    def child(self, row: int) -> Optional['Dataset']:
        if row < 0 or row >= len(self.datasetsStore):
            return None
        return list(self.datasetsStore.items())[row][1]

    def columnName(self, column: int) -> Optional[str]:
        return None

    def sync(self):
        """Method to sync with Datasets available in "trends_earth/advanced/base_data_directory".

        The method parse content o base_data_directory and create Dataset instance for each 
        found Dataset descriptor.
        """
        base_data_directory = QSettings().value("trends_earth/advanced/base_data_directory", None, type=str)

        def traverse(path):
            excluded_path = os.path.sep + 'Jobs' + os.path.sep

            for basepath, directories, files in os.walk(path):
                for f in files:
                    # skip files in Jobs
                    if excluded_path.lower() in basepath.lower():
                        continue

                    yield os.path.join(basepath, f)

        # remove any previous memorised Datasets
        # self.reset()
        schema = DatasetSchema()
        for json_file in traverse(base_data_directory):
            # skip larger thatn 1MB files
            statinfo = os.stat(json_file)
            if statinfo.st_size > 1024 * 1024:
                continue

            # skip any non json file
            with open(json_file, 'r') as fd:
                try:
                    parsed_json = json.load(fd)
                except json.decoder.JSONDecodeError as ex:
                    # no json => skip
                    continue
                except Exception as ex:
                    log(tr('Error reading file {} with ex: ').format(json_file, str(ex)))
                    continue

                try:
                    dataset_dict = schema.load(parsed_json, partial=True, unknown=marshmallow.INCLUDE)
                    dataset = Dataset(dataset=dataset_dict)
                    self.datasetsStore[json_file] = dataset

                except marshmallow.exceptions.ValidationError as ex:
                    log(tr('not a valid Dataset {} with ex: ').format(f, str(ex)))
                    continue
                except Exception as ex:
                    # Exception notification managed in append method
                    log(tr('Cannot manage dataset for file {} ex: {}').format(json_file, str(ex)))
                    continue
        self.updated.emit()


class DatasetSchema(Schema):
    """Schema defining structure of a dumped Dataset.
    """
    # job = fields.Nested(APIResponseSchema, many=False, required=False)
    job = fields.Str(required=False)

    status = fields.Str(required=True)
    # status = fields.Str(
    #     validate=validate.OneOf(DatasetStatusStrings), 
    #     required=True
    # )
    progress = fields.Integer(required=True)
    source = fields.Str(required=True)
    name = fields.Str()
    creation_date = fields.DateTime(required=True)
    run_id = fields.UUID(required=True)
