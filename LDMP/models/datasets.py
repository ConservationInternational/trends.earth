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

from typing import Optional, Union, List
from datetime import datetime
from enum import Enum
import abc
import os
import json

from qgis.PyQt.QtCore import QSettings
from LDMP.jobs import Job, JobSchema
from LDMP import log

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


class DatasetSource(object):
    def __init__(self):
        super().__init__()

# implemented a base class in case need to expand the three with new nodes
class DatasetBase(abc.ABC):

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

# Datasets is a class placeholder to be root of the tree. It shouldn't be
# necessary in case of using QListView, but using TreeView to allow
# more flexibility
class Datasets(object):
    datasets: List[Dataset]

    def __init__(self, datasets: Optional[List[Dataset]] = None):
        super().__init__()
        self.datasets = list(datasets) if datasets is not None else []

    # method useful to interface with MVC model
    def columnCount(self) -> int:
        return 1

    def rowCount(self) -> int:
        return len(self.datasets)
    
    def child(self, row: int) -> Optional['Dataset']:
        if row < 0 or row >= len(self.datasets):
            return None
        return self.datasets[row]
    
    def columnName(self, column: int) -> Optional[str]:
        return None

    # methods to manage sync with Jobs in base_data_directory
    def sync(self):
        """Method to sync with jobs available in "trends_earth/advanced/base_data_directory".

        The method parse content o base_data_directory and create Dataset instalce for each 
        found Job.
        Jobs in base_data_directory can be seen as a cache of Jobs at server side.
        """
        base_data_directory = QSettings().value("trends_earth/advanced/base_data_directory", None, type=str)
        job_schema = JobSchema()

        def traverse(path):
            for basepath, directories, files in os.walk(path):
                for f in files:
                    yield os.path.join(basepath, f)
        for f in traverse(base_data_directory):
            # skip larger thatn 1MB files
            statinfo = os.stat(f)
            if statinfo.st_size > 1024*1024:
                continue

            # skip any not json file
            with open(f, 'r') as fd:
                try:
                    parsed_json = json.load(fd)
                except json.decoder.JSONDecodeError as ex:
                    # no json => skip
                    continue
                except Exception as ex:
                    log('Error reading file {} with ex: '.format(f, str(ex)))
                    continue
            
                # check if it is a Job parsing with schema
                try:
                    response = job_schema.load(parsed_json, partial=True, unknown=marshmallow.INCLUDE)
                except marshmallow.exceptions.ValidationError as ex:
                    log('not a valid Job {} with ex: '.format(f, str(ex)))
                    continue
                job = Job(response['response'])

                # create Job's related Dataset adding to the "Datasets"
                ds = Dataset(job)
                self.datasets.append(ds)





