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

from typing import Optional, Union, List, Dict, Tuple
from datetime import datetime
from enum import Enum
import abc
import os
import json
from collections import OrderedDict
import threading
import glob
import shutil

from qgis.utils import iface
from qgis.PyQt.QtCore import QSettings, pyqtSignal, QObject
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import QgsLogger
from LDMP.jobs import Job, JobSchema, Jobs, download_cloud_results, download_timeseries
from LDMP.calculate import get_script_group
from LDMP import log, singleton, tr, json_serial, traverse

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


class SortField(Enum):
    NAME = 'name'
    DATE = 'date'
    ALGORITHM = 'algorithm'
    STATUS = 'status'


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
    downloaded = pyqtSignal(str)
    deleted = pyqtSignal(str)
    class Origin(Enum):
        job = 0,
        dataset = 1,
        downloaded_dataset = 2,
        not_applicable = 3

    def __init__(self,
            job: Optional[Job] = None,
            dataset: Optional[Dict] = None,
            filename: Optional[str] = None
        ) -> None:
        super().__init__()

        self.__origin = Dataset.Origin.not_applicable
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

            self.__origin = Dataset.Origin.job
            self.__fileName = None

        elif dataset:
            # check if refer to a Dataset or Downloaded dataset
            if 'bands' in dataset:
                self.bands = dataset.get('bands')
                self.file = dataset.get('file')
                self.metadata = dataset.get('metadata')

                # set common dataset data get from medatata (e.g. original Job)
                self.status = self.metadata.get('status')
                self.progress = self.metadata.get('progress')
                self.source = self.metadata.get('script_name')
                self.name = self.metadata.get('task_name')
                self.creation_date = self.metadata.get('start_date')
                self.run_id = self.metadata.get('id')

                self.__origin = Dataset.Origin.downloaded_dataset
                self.__fileName = filename

            else:
                self.job = ''

                self.status = dataset.get('status')
                # self.status: DatasetStatus = getStatusEnum(job.status)
                self.progress = dataset.get('progress')
                self.source = dataset.get('source')
                self.name = dataset.get('name')
                self.creation_date = dataset.get('creation_date')
                self.run_id = dataset.get('run_id')

                self.__origin = Dataset.Origin.dataset
                self.__fileName = filename
        else:
            raise Exception('Nor input Job or dataset dictionary are set to build a Dataset instance')

    def origin(self) -> 'Dataset.Origin':
        return self.__origin

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
        # for now only 'outputs'
        out_path = os.path.join(base_data_directory, 'outputs')

        # set location where to save basing on script(alg) used
        if self.origin() != Dataset.Origin.downloaded_dataset:
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

        schema = DatasetSchema()
        with open(descriptor_file_name, 'w') as f:
            json.dump(
                schema.dump(self),
                f, default=json_serial, sort_keys=True, indent=4, separators=(',', ': ')
            )
        self.dumped.emit(descriptor_file_name)

        self.__fileName = descriptor_file_name
        return descriptor_file_name

    def fileName(self):
        return self.__fileName

    @staticmethod
    def datetimeRepr(dt: datetime) -> str:
        return datetime.strftime(dt, '%Y/%m/%d (%H:%M)')

    @staticmethod
    def toDatetime(dt: str, fmt: str = None) -> datetime:
        if fmt is None:
            return datetime.fromisoformat(dt)
        return datetime.strptime(dt, fmt)

    def download(self, datasets_refresh: bool = True, add_to_map: bool = False) -> None:
        """Download Dataset related to a specified Job in a programmatically defined filename and folder.
        Because a new dataset JSON descriptor is created => Datasets sync

        Args:
            datasets_refresh (bool): if have to trigger Datasets().sync() after downloaded.

        Returns:
            None
        """
        res = Jobs().jobById(str(self.run_id)) # casting because can be UUID
        if res is None:
            log(tr('No Job available in cache with run id: {}').format(str(self.run_id)))
            return
        job_filename, job = res # unwrap tuple

        # get path of the current dataset descriptos
        res = Datasets().datasetById(str(self.run_id)) # casting because can be UUID
        if res is None:
            log(tr('No Dataset available in cache with run id: {}').format(str(self.run_id)))
            return
        dataset_filename = res[0]

        # Check if we need a download filename - some tasks don't need to 
        # save data, but if any of the chosen tasks do, then we need to 
        # choose a folder. Right now only TimeSeriesTable doesn't need a 
        # filename.
        base_dir = os.path.dirname(dataset_filename)
        f = None
        if job.results.get('type') != 'TimeSeriesTable':
            # create result filename basing on:
            # run_id + scriptName + task_name (if any)
            fileBaseName = None
            if job.taskName:
                fileBaseName = u'{}_{}_{}'.format(job.runId, job.scriptName, job.taskName)
            else:
                fileBaseName = u'{}_{}'.format(job.runId, job.scriptName)
            
            # set the folder where to save result
            f = os.path.join(base_dir, fileBaseName)
            log(u"Downloading results to {} with basename {}".format(os.path.dirname(f), os.path.basename(f)))

        log(u"Processing job {}.".format(job.runId))
        result_type = job.results.get('type')
        if result_type == 'CloudResults':
            download_cloud_results(job.raw, f, self.tr, add_to_map=add_to_map)
            self.downloaded.emit(f)
            if datasets_refresh:
                Datasets().sync()
        elif result_type == 'TimeSeriesTable':
            download_timeseries(job.raw, self.tr)
            self.downloaded.emit(None)
            if datasets_refresh:
                Datasets().sync()
        else:
            raise ValueError("Unrecognized result type in download results: {}".format(result_type))

    def delete(self, ask_confirmation=True):
        """Download a downloaded dataset. E.g. remove any downloaded file and move descriptor only in
        a Delete folder to take trace of deleted one and avoid to doenload again.
        """
        json_path = os.path.dirname(self.__fileName)

        if iface and ask_confirmation:
            identifier = self.name if self.name else self.run_id
            resp = QMessageBox.question(iface.mainWindow(),
                    self.tr(f'Deleting dataset'),
                    self.tr(f'Do you really want to delete: {identifier}'),
                    QMessageBox.Yes|QMessageBox.No, QMessageBox.NoButton)
            if resp == QMessageBox.No:
                return

        # copy json descriptor in delete folder
        base_data_directory = QSettings().value("trends_earth/advanced/base_data_directory", None, type=str)
        if base_data_directory is None:
            return
        delete_path = os.path.join(base_data_directory, 'deleted')

        if not os.path.exists(delete_path):
            os.makedirs(delete_path)
        try:
            shutil.copy(self.__fileName, delete_path)
        except Exception as ex:
            log(tr(f'Cannot copy file: {self.__fileName} to path: {delete_path}'))
            QgsLogger.debug(f'{str(ex)}', debuglevel=1)
            return

        # look for all run_id related files
        look_for = os.path.join(json_path, f"{self.run_id}*")
        related = glob.glob(look_for, recursive=False)
        for f in related:
            # remove related
            try:
                os.remove(f)
            except Exception as ex:
                QgsLogger.debug(f'{str(ex)}', debuglevel=1)
                pass
        self.deleted.emit(self.__fileName)

    def add(self):
        """Add dataset in canvas.
        Reused completly download method to try to use old code as back box and avoid introduce any
        changes. Datasets already downloaded will not downloaded again.
        """
        self.download(datasets_refresh=False, add_to_map=True)

@singleton
class Datasets(QObject):
    """Singleton container to separate Dialog to Job operations as retrieve and update.
    
    It shouldn't be necessary in case of using QListView, but using TreeView to allow
    more flexibility.
    """
    datasetsStore: Dict[str, Dataset] = OrderedDict()
    updated = pyqtSignal()
    lock = threading.RLock()

    def __init__(self):
        super().__init__()

    def reset(self, emit: bool = True):
        """Remove any Datast and related json contrepart."""
        # remove any json of the available Jobs in self.jobs
        # for file_name in self.datasetsStore.keys():
        #     os.remove(file_name)
        with self.lock:
            self.datasetsStore = OrderedDict()

        if emit:
            self.updated.emit()

    def appendFromJob(self, job: Job) -> (str, Dataset):
        """Create a Dataset and dump basing an assumed valid Job."""
        # do nothing if dataset has been marked as deleted
        base_data_directory = QSettings().value("trends_earth/advanced/base_data_directory", None, type=str)
        if not base_data_directory:
            return
        deleted_subpath = os.path.join(base_data_directory, 'deleted')

        # get list of all deleted Datasets
        deleted = traverse(deleted_subpath)

        # check if already deleted
        is_deleted = next((d for d in deleted if job.runId in d), None)
        if is_deleted:
            return

        # not deleted => create Dataset
        dataset = Dataset(job=job)
        dataset.deleted.connect(self.sync)
        dump_file_name = dataset.dump() # doing save in default location

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
        if not base_data_directory:
            return
        jobs_subpath = os.path.join(base_data_directory, 'Jobs')
        deleted_subpath = os.path.join(base_data_directory, 'deleted')

        datasetSchema = DatasetSchema()
        downloadedDatasetSchema = DownloadedDatasetSchema()

        # remove any previous memorised Datasets
        self.reset(emit=False)

        # get all deleted Datasets descriptos
        deleted = list(traverse(deleted_subpath))

        # purge all too old deleted descriptors
        today = datetime.today()
        deleted_datasets_age_limit = QSettings().value("trends_earth/advanced/deleted_datasets_age_limit", 15, type=int)
        for deleted_json in deleted:
            creation_datetime = os.stat(deleted_json).st_ctime
            creation_datetime = datetime.fromtimestamp(creation_datetime)
            delta = today - creation_datetime
            if delta.days > deleted_datasets_age_limit:
                try:
                    os.remove(json_file)
                except:
                    pass

        # process all available Dataset descriptors
        json_files = list(traverse(base_data_directory, excluded=[jobs_subpath, deleted_subpath])) # need traverse all to check if some dataset has been already downloaded
        for json_file in json_files:
            # skip larger thatn 1MB files
            statinfo = os.stat(json_file)
            if statinfo.st_size > 1024*1024:
                continue

            # Datasets descriptor json filenamehas these relations:
            #   Dataset descriptor: b4b098f8-e562-4843-b6ed-586878410a01.json
            #   Downloaded dataset descriptor: b4b098f8-e562-4843-b6ed-586878410a01_Productivity 1_0_3_gen_test19.json
            # A deleted descriptor is moved in "deleted" folder
            basename_uuid = os.path.splitext(os.path.basename(json_file))[0]

            # skip if Dataset has been deleted
            been_deleted = next((d for d in deleted if basename_uuid in d), None)
            if been_deleted:
                # if strored in datasetStore remove entry related to deleted Dataset
                self.datasetsStore.pop(json_file, None)

                # remove also the dataset json in case it's still present
                try:
                    os.remove(json_file)
                except:
                    pass
                QgsLogger.debug(f'Dataset {json_file} already marked as deleted => skipped', debuglevel=3)
                continue

            # skip if dataset has a downloaded contrepart e.g. a json file with the same UUID plus more
            # info in filename
            look_for = basename_uuid + "_"
            found = next((j for j in json_files if look_for in j), None) # look if some key containing 'look_for' string
            if found:
                # if strored in datasetStore remove entry related to json_file Dataset
                self.datasetsStore.pop(json_file, None)

                # remove also the dataset json that now is nomore necessary
                try:
                    os.remove(json_file)
                except:
                    pass
                QgsLogger.debug(f'Dataset {json_file} already downloaded => skipped', debuglevel=3)
                continue

            # skip any not json file
            with open(json_file, 'r') as fd:
                try:
                    parsed_json = json.load(fd)
                except json.decoder.JSONDecodeError as ex:
                    # no json => skip
                    continue
                except Exception as ex:
                    # because reach codec error trying to parse .tiff => avoid to clutter log
                    extension = os.path.splitext(json_file)[1]
                    if extension.lower() not in ['tif', 'tiff', 'png', 'jpeg', 'jpg']:
                        QgsLogger.debug('* Error reading file {} with ex: {}'.format(json_file, str(ex)), debuglevel=3)
                    continue

                # block useful to distinguish if dataset is a downloaded dataset or not
                dataset_dict = None
                try:
                    # check if DownloadedDataset
                    dataset_dict = downloadedDatasetSchema.load(parsed_json, partial=False, unknown=marshmallow.RAISE)

                except marshmallow.exceptions.ValidationError as ex:

                    # now check if a normal Dataset (not yet donwloaded). e.g. previous schema parse failed
                    try:
                        dataset_dict = datasetSchema.load(parsed_json, partial=True, unknown=marshmallow.INCLUDE)

                    except marshmallow.exceptions.ValidationError as ex:
                        log(tr('not a valid Dataset {} with ex: {}').format(f, str(ex)))
                        continue

                except Exception as ex:
                    # Exception notification managed in append method
                    log(tr('Cannot manage dataset for file {} ex: {}').format(json_file, str(ex)))
                    continue
                
                if dataset_dict:
                    dataset = Dataset(dataset=dataset_dict, filename=json_file)
                    dataset.deleted.connect(self.sync)
                    self.datasetsStore[json_file] = dataset

        self.updated.emit()

    def triggerDownloads(self) -> None:
        """Method to start download for each Dataset in the following state:
        1) successufully finished e.g. dataset.status in ['FINISHED', 'SUCCESS']
        2) dataset.origin == Dataset.Origin.dataset (e.g. not yet downloaded).
        """
        for json_file, dataset in self.datasetsStore.items():
            if ( (dataset.status not in ['FINISHED', 'SUCCESS']) or
                 (dataset.origin() != Dataset.Origin.dataset) ):
                continue
            # do not refresh datasets and do only after triggered all downloads
            dataset.download(datasets_refresh=False)
        self.sync()

    def datasetById(self, id: str) -> Optional[Tuple[str, Job]]:
        """Return Dataset and related descriptor asociated file."""
        datasets = [(k, d) for k,d in self.datasetsStore.items() if str(d.run_id) == id]
        return datasets[0] if len(datasets) else None

    def sort(self, column, order, field: SortField):
        self.datasetsStore = OrderedDict(self.__merge_sort(list(self.datasetsStore.items()), field))

    def __merge_sort(self, items: List, field):
        if len(items) <= 1:
            return items
        mid = int((len(items) / 2))

        left = self.__merge_sort(items[:mid], field)
        right = self.__merge_sort(items[mid:], field)
        return self.__merge(left, right, field)

    def __merge(self, left, right, field):
        sorted_dict = []
        i = j = 0

        while i < len(left) and j < len(right):
            if self.__less_than(left[i][1], right[j][1], field):
                sorted_dict.append(left[i])
                i += 1
            else:
                sorted_dict.append(right[j])
                j += 1
        sorted_dict.extend(left[i:])
        sorted_dict.extend(right[j:])
        return sorted_dict

    def __less_than(self, left_dataset, right_dataset, field: SortField):
        if field == SortField.NAME:
            return left_dataset.name < right_dataset.name
        elif field == SortField.DATE and \
                isinstance(left_dataset.creation_date, datetime) \
                and isinstance(right_dataset.creation_date, datetime):
            return left_dataset.creation_date < right_dataset.creation_date
        elif field == SortField.ALGORITHM:
            return left_dataset.source < right_dataset.source
        elif field == SortField.STATUS:
            return left_dataset.status < right_dataset.status
        return False


class DatasetSchema(Schema):
    """Schema defining structure of a dumped Dataset.
    !!! BEAWARE !!! this schema represent only a dataset not yet downloaded.
    A downloaded dataset has a different schema as described in DownloadedDatasetSchema
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


class DownloadedDatasetSchema(Schema):
    """Schema defining structure of a dounloaded Dataset.
    !!! BEAWARE !!! this schema represent only a dataset ALREADY downloaded.
    A "TO DOWNLOAD" dataset has a different schema as described in
    DatasetSchema
    """
    # bands leaved with a fixed schema
    bands = fields.List(fields.Dict(required=True), required=True)

    file = fields.Str(required=True)
    metadata = fields.Nested(JobSchema, many=False, required=False)


