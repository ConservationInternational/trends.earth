import enum
import typing


class AlgorithmNodeType(enum.Enum):
    Group = 1
    Algorithm = 2
    Details = 3


class AlgorithmRunMode(enum.Enum):
    NOT_APPLICABLE = 0
    LOCAL = "local"
    REMOTE = "remote"
    BOTH = "both"


class AlgorithmGroup:
    name: str
    name_details: str
    parent: typing.Optional["AlgorithmGroup"]
    algorithms: typing.List["AlgorithmDescriptor"]
    groups: typing.List["AlgorithmGroup"]
    item_type: AlgorithmNodeType = AlgorithmNodeType.Group

    def __init__(
            self,
            name: str,
            name_details: typing.Optional[str] = "",
            parent: typing.Optional['AlgorithmGroup'] = None,
            algorithms: typing.Optional[typing.List["AlgorithmDescriptor"]] = None,
            groups: typing.Optional[typing.List["AlgorithmGroup"]] = None,
    ) -> None:
        self.name = name
        self.name_details = name_details
        self.parent = parent
        self.algorithms = []
        for alg in algorithms or []:
            alg.parent = self
            self.algorithms.append(alg)
        self.groups = []
        for group in groups or []:
            group.parent = self
            self.groups.append(group)

    @classmethod
    def deserialize(cls, raw_group: typing.Dict):
        child_algorithms = []
        for raw_algorithm in raw_group.get("algorithms", []):
            algorithm = AlgorithmDescriptor.deserialize(raw_algorithm)
            child_algorithms.append(algorithm)
        child_groups = []
        for raw_child_group in raw_group.get("groups", []):
            child_group = AlgorithmGroup.deserialize(raw_child_group)
            child_groups.append(child_group)
        return cls(
            name=raw_group.get("name", ""),
            name_details=raw_group.get("name_details", ""),
            algorithms=child_algorithms,
            groups=child_groups
        )


class AlgorithmDescriptor:
    brief_description: str
    description: str
    execution_dialogues: typing.Mapping[AlgorithmRunMode, typing.Callable]
    item_type: AlgorithmNodeType = AlgorithmNodeType.Algorithm

    def __init__(
            self,
            name: str,
            execution_dialogues: typing.Mapping[AlgorithmRunMode, typing.Callable],
            name_details: typing.Optional[str] = "",
            brief_description: typing.Optional[str] = "",
            description: typing.Optional[str] = "",
            parent: typing.Optional[AlgorithmGroup] = None,
    ) -> None:
        self.name = name
        self.name_details = name_details
        self.parent = parent
        self.execution_dialogues = dict(execution_dialogues)
        self.description = description
        self.brief_description = brief_description

    @property
    def run_modes(self) -> typing.List[AlgorithmRunMode]:
        return list(self.execution_dialogues.keys())

    @classmethod
    def deserialize(cls, raw_algorithm: typing.Dict):
        execution_dialogues = {}
        for run_mode, class_path in raw_algorithm.get("run_modes", {}).items():
            mode = AlgorithmRunMode(run_mode)
            execution_dialogues[mode] = class_path
        return cls(
            name=raw_algorithm.get("name", ""),
            name_details=raw_algorithm.get("name_details", ""),
            brief_description=raw_algorithm.get("brief_description", ""),
            description=raw_algorithm.get("description", ""),
            execution_dialogues=execution_dialogues
        )