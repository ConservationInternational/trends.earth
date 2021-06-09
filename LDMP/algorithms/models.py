import dataclasses
import enum
import functools
import typing
import uuid


class AlgorithmNodeType(enum.Enum):
    Group = 1
    Algorithm = 2
    Details = 3


class AlgorithmRunMode(enum.Enum):
    NOT_APPLICABLE = 0
    LOCAL = "local"
    REMOTE = "remote"
    BOTH = "both"


@dataclasses.dataclass()
class ExecutionScript:
    name: str
    run_mode: AlgorithmRunMode
    id: typing.Optional[uuid.UUID] = None
    version: typing.Optional[str] = ""
    description: typing.Optional[str] = ""
    additional_configuration: typing.Optional[typing.Dict] = None

    @property
    def slug(self) -> str:
        return self.name.replace(" ", "-").lower()

    @classmethod
    def deserialize(cls, name: str, raw_script: typing.Dict):
        raw = dict(raw_script)
        run_mode = AlgorithmRunMode(raw.pop("run_mode"))
        raw_id = raw.pop("id", None)
        version = raw.pop("version", "")
        description = raw.pop("description", "")
        return cls(
            name=name,
            id=uuid.UUID(raw_id) if raw_id is not None else None,
            version=version,
            run_mode=run_mode,
            description=description,
            additional_configuration=raw
        )

    @classmethod
    def deserialize_from_remote_response(cls, raw_remote_script: typing.Dict):
        return cls(
            name=raw_remote_script["name"],
            run_mode=AlgorithmRunMode.REMOTE,
            id=uuid.UUID(raw_remote_script["id"]),
            description=raw_remote_script["description"],
        )


@dataclasses.dataclass()
class AlgorithmScript:
    script: ExecutionScript
    parametrization_dialogue: str

    @classmethod
    def deserialize(cls, raw_script_config: typing.Dict):
        return cls(
            script=raw_script_config["script"],
            parametrization_dialogue=raw_script_config["parametrization_dialogue"]
        )


class AlgorithmGroup:
    name: str
    name_details: str
    parent: typing.Optional["AlgorithmGroup"]
    algorithms: typing.List["Algorithm"]
    groups: typing.List["AlgorithmGroup"]
    item_type: AlgorithmNodeType = AlgorithmNodeType.Group

    def __init__(
            self,
            name: str,
            name_details: typing.Optional[str] = "",
            parent: typing.Optional['AlgorithmGroup'] = None,
            algorithms: typing.Optional[typing.List["Algorithm"]] = None,
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
            algorithm = Algorithm.deserialize(raw_algorithm)
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


class Algorithm:
    name: str
    scripts: typing.List[AlgorithmScript]
    name_details: typing.Optional[str]
    brief_description: typing.Optional[str]
    description: typing.Optional[str]
    parent: typing.Optional[AlgorithmGroup]
    item_type: AlgorithmNodeType = AlgorithmNodeType.Algorithm

    def __init__(
            self,
            name: str,
            scripts: typing.List[AlgorithmScript],
            name_details: typing.Optional[str] = "",
            brief_description: typing.Optional[str] = "",
            description: typing.Optional[str] = "",
            parent: typing.Optional[AlgorithmGroup] = None,
    ) -> None:
        self.name = name
        self.scripts = list(scripts)
        self.name_details = name_details
        self.description = description
        self.brief_description = brief_description
        self.parent = parent

    @classmethod
    def deserialize(
            cls,
            raw_algorithm: typing.Dict,
    ):
        scripts = []
        for raw_script_config in raw_algorithm["scripts"]:
            scripts.append(AlgorithmScript.deserialize(raw_script_config))
        return cls(
            name=raw_algorithm["name"],
            name_details=raw_algorithm.get("name_details", ""),
            brief_description=raw_algorithm.get("brief_description", ""),
            description=raw_algorithm.get("description", ""),
            scripts=scripts,
        )