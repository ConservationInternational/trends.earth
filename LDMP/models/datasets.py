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

class DatasetStatus(Enum):
    available = 0,
    being_generated = 1,
    downloading = 2,
    unavailable = 3,
    not_applicable = 4


class DatasetSource(object):
    def __init__(self):
        super().__init__()


# implemented a base class in case need to expand the three with new nodes
class DatasetBase(abc.ABC):

    def __init__(self,
            name: str,
            creation_date: datetime,
            source: str
        ) -> None:
        super().__init__()
        self.status: DatasetStatus = DatasetStatus.not_applicable
        self.source = source
        self.name = name
        self.creation_date = creation_date

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
            name: str,
            creation_date: datetime,
            source: str
        ) -> None:
        super().__init__(name, creation_date, source)
        self.status: DatasetStatus = DatasetStatus.not_applicable
        self.source = source
        self.name = name
        self.creation_date = creation_date

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
    def __init__(self):
        super().__init__()
        self.datasets: List[Dataset] = []

    def columnCount(self) -> int:
        return 1

    def rowCount(self) -> int:
        return len(self.datasets)
    
    def child(self, row: int) -> Union['Dataset', None]:
        if row < 0 or row >= len(self.datasets):
            return None
        
        return self.datasets[row]
    
    def columnName(self, column: int) -> Union[str, None]:
        return None
