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


class DatasetStatus(Enum):
    available = 0,
    being_generated = 1,
    downloading = 2,
    unavailable = 3,
    not_applicable = 4


def getStatusEnum(status: str) -> DatasetStatus:
    # get APIResponseSchema and remap into DatasetStatus
    ds_status = DatasetStatus.not_applicable
    if status in ['PENDING']:
        ds_status = DatasetStatus.being_generated
    elif status in ['SUCCESS']:
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

    # def __init__(self,
    #         name: str,
    #         creation_date: datetime,
    #         source: str,
    #         run_id: str
    #     ) -> None:
    #     super().__init__()
    #     self.status: DatasetStatus = DatasetStatus.not_applicable
    #     self.source = source
    #     self.run_id = run_id
    #     self.name = name
    #     self.creation_date = creation_date

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
            job: Job,
        ) -> None:
        super().__init__()

        self.status: DatasetStatus = getStatusEnum(job.status)
        self.progress = job.progress
        self.source = job.scriptName
        self.name = job.taskName
        self.creation_date = job.startDate
        self.run_id = job.runId

    # def __init__(self,
    #         name: str,
    #         creation_date: datetime,
    #         source: str,
    #         run_id: str,
    #     ) -> None:
    #     super().__init__(name, creation_date, source, run_id)
    #     self.status: DatasetStatus = DatasetStatus.not_applicable
    #     self.source = source
    #     self.name = name
    #     self.creation_date = creation_date

    def columnCount(self) -> int:
        return 1

    def rowCount(self) -> int:
        return 0
    
    def child(self, row: int) -> None:
        return None
    
    def columnName(self, column: int) -> Union[str, None]:
        return None

    def dump(self) -> str:
        """Dump Dataset as JSON in a programmatically set folder with a programmaticaly set filename.
        """
        # create path and filname where to dump Job descriptor
        out_path = ''
        base_data_directory = QSettings().value("trends_earth/advanced/base_data_directory", None, type=str)

        # TODO: set subfolder basing on the nature of Dataset
        # for now only 'ouptuts'
        out_path = os.path.join(base_data_directory, 'ouptuts')

        # set location where to save basing on script(alg) used
        script_name = self.source
        components = script_name.split()
        components = components[:-1] if len(components) > 1 else components # eventually remove version that return when get exeutions list
        formatted_script_name = '-'.join(components) # remove al version and substitutes ' ' with '-'
        formatted_script_name = formatted_script_name.lower()

        # get alg group to setup subfolder
        group = get_script_group(formatted_script_name)
        if not group:
            log(tr('Cannot get group of the script: ') + formatted_script_name)
            group = 'UNKNOW_GROUP_FOR_' + formatted_script_name

        # get exectuion date as subfolder name
        processing_date_string = self.creation_date
        if isinstance(processing_date_string, datetime):
            processing_date_string = self.creation_date.strftime('%Y_%m_%d')

        out_path = os.path.join(out_path, group, processing_date_string)
        if not os.path.exists(out_path):
            os.makedirs(out_path)

        descriptor_file_name = self.run_id + '.json'
        descriptor_file_name = os.path.join(out_path, descriptor_file_name)
        QgsLogger.debug('* Dump dataset descriptor into file: '+ descriptor_file_name, debuglevel=4)

        # check if it is a Job parsing with schema
        # Datasets and Jobs historically share the same json structure
        # so continue using JobSchema to parse it
        job_schema = JobSchema()
        with open(descriptor_file_name, 'w') as f:
            json_to_write = json.dump(
                job_schema.dump(self),
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
        """Remove any Datast and related json contrepart."""
        # remove any json of the available Jobs in self.jobs
        for file_name in self.datasetsStore.keys():
            os.remove(file_name)
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

    # def list(self):
    #     """Get only values of the ordered dict."""
    #     return [pair[1] for pair in self.datasetsStore.items()]

    def append(self, dataset_dict: dict):
        """Append a dataset dictionay in base_data_directory."""
        # Create data set instance using schema Job validation
        schema = JobSchema()
        try:
            response = schema.load(dataset_dict, partial=True, unknown=marshmallow.INCLUDE)
        except marshmallow.exceptions.ValidationError as ex:
            log(tr('not a valid Job {} with ex: ').format(f, str(ex)))
            raise ex

        if 'response' in response:
            response = response['response']
        job = Job(response)
        dataset = Dataset(job)
        dump_file_name = dataset.dump() # doing save in default location

        # add in memory store .e.g a dictionary
        self.datasetsStore[dump_file_name] = dataset

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
        job_schema = JobSchema()

        def traverse(path):
            # excluded_path = os.path.sep + 'Jobs' + os.path.sep

            for basepath, directories, files in os.walk(path):
                for f in files:
                    # skip files in Jobs
                    if excluded_path.lower() in basepath.lower():
                        continue

                    yield os.path.join(basepath, f)

        # remove any previous saved Datasets
        self.reset()

        for json_file in traverse(base_data_directory):
            # skip larger thatn 1MB files
            statinfo = os.stat(json_file)
            if statinfo.st_size > 1024*1024:
                continue

            # skip any not json file
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
                    self.append(parsed_json)
                except Exception as ex:
                    # Exception notification managed in append method
                    log(tr('Cannot dump dataset for file {} ex: {}').format(json_file, str(ex)))
                    continue
        self.updated.emit()





