"""
/***************************************************************************
 LDMP - A QGIS plugin
 This plugin supports monitoring and reporting of land degradation to the UNCCD 
 and in support of the SDG Land Degradation Neutrality (LDN) target.
                              -------------------
        begin                : 2021-02-25
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Conservation International
        email                : trends.earth@conservation.org
 ***************************************************************************/
"""

__author__ = 'Luigi Pirelli / Kartoza'
__date__ = '2021-03-03'

from typing import Optional, Union, List
from enum import Enum
import abc

from marshmallow import Schema, fields, post_load

class AlgorithmNodeType(Enum):
    Group = 1,
    Leaf = 2


class AlgorithmRunMode(Enum):
    NotApplicable = 0,
    Locally = 1,
    Remotely = 2,
    Both = 3


class AlgorithmBase(abc.ABC):

    def __init__(self,
            name: str,
            name_details: Optional[str] = None,
            group: 'AlgorithmGroup' = None, # string because forwarde declared class
        ) -> None:
        super().__init__()
        self.algorithm_type: Optional[AlgorithmNodeType] = None
        self.group = group
        self.name = name
        self.name_details = name_details

    def getGroup(self) -> 'AlgorithmBase':
        return self.group

    def row(self) -> int:
        if not self.group:
            # e.g. root node/group
            return 0
        
        # look for self in parent group.algorithms
        try:
            return self.group.algorithms.index(self)
        except ValueError as ex:
            # something strange happen. Can't find myself
            return 0

    @abc.abstractmethod
    def rowCount(self) -> int:
        pass

    @abc.abstractmethod
    def columnCount(self) -> int:
        pass

    @abc.abstractmethod
    def child(self, row) -> Union['AlgorithmBase', None]: # string because AlgorithmBase not yet completly defined
        pass

class AlgorithmGroup(AlgorithmBase):

    def __init__(self,
            name: str,
            name_details: Optional[str],
            group: 'AlgorithmGroup',
            algorithms: List[Union['AlgorithmDescriptor', 'AlgorithmGroup']]
        ) -> None:
        super().__init__(name, name_details, group)
        self.type = AlgorithmNodeType.Group
        self.group = group
        self.name = name
        self.name_details = name_details
        self.algorithms = algorithms

    def columnCount(self) -> int:
        return 2

    def rowCount(self) -> int:
        return len(self.algorithms)
    
    def child(self, row: int) -> Union['AlgorithmBase', None]:
        if row < 0 or row >= len(self.algorithms):
            return None
        
        return self.algorithms[row]
    
    def columnName(self, column: int) -> Union[str, None]:
        if column == 0:
            return 'Description'
        if column == 1:
            return 'widget'
        
        return None



class AlgorithmDescriptor(AlgorithmBase):
    def __init__(self,
            name: str,
            name_details: Optional[str],
            brief_description: str,
            description: str,
            group: AlgorithmGroup, # e.g. an Alg can belogs to only a group => 1 to 1 limitation!
            run_mode: AlgorithmRunMode = AlgorithmRunMode.Locally,
        ) -> None:
        super().__init__(name, name_details, group)
        self.type = AlgorithmNodeType.Leaf
        self.group = group

        self.name = name
        self.name_details = name_details
        self.brief_description = brief_description,
        self.description = description
        self.run_mode = AlgorithmRunMode.Remotely,

    def columnCount(self) -> int:
        return 2
    
    def rowCount(self) -> int:
        return 0

    def child(self, row: int) -> None:
        return None
