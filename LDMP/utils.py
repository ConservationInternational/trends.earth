import importlib
import typing


def load_object(python_path: str) -> typing.Any:
    module_path, object_name = python_path.rpartition(".")[::2]
    loaded_module = importlib.import_module(module_path)
    return getattr(loaded_module, object_name)
