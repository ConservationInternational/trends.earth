# -*- coding: utf-8 -*-
""" Trends Earth plugin admin operations,
    including packaging, deployment and GitHub releases.
"""

import datetime as dt
import shlex
import shutil
import subprocess
import typing
import zipfile
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import httpx
import typer

LOCAL_ROOT_DIR = Path(__file__).parent.resolve()
SRC_NAME = "trends.earth"
PLUGIN_PACKAGE = "LDMP"

PACKAGE_NAME = SRC_NAME.replace("_", "")
ICON_PATH = "resources/img/icons/icon.png"

TEST_FILES = [
    "docker-compose.yml",
    "scripts",
    "test",
    "test_suite.py",
]

PLUGIN_FILES = [
    "__init__.py",
    "LDMP",
    "metadata.txt",
    "LICENSE"
    "README.html",
    "README.md"
]
app = typer.Typer()


@dataclass
class GithubRelease:
    """
    Class for defining plugin releases details.
    """
    pre_release: bool
    tag_name: str
    url: str
    published_at: dt.datetime


@app.callback()
def main(
        context: typer.Context,
        verbose: bool = False,
        qgis_profile: str = "default"):
    """Performs various development-oriented tasks for this plugin
    :param context: Application context
    :type context: typer.Context
    :param verbose: Boolean value to whether more details should be displayed
    :type verbose: bool
    :param qgis_profile: QGIS user profile to be used when operating in
            QGIS application
    :type qgis_profile: str
    """
    context.obj = {
        "verbose": verbose,
        "qgis_profile": qgis_profile,
    }


@app.command()
def generate_zip(
        context: typer.Context,
        output_directory: typing.Optional[Path] = LOCAL_ROOT_DIR / "dist",
        version: str = "1.0.0"):
    """ Generates plugin zip folder, that can be used to installed the
        plugin in QGIS
    :param context: Application context
    :type context: typer.Context
    :param output_directory: Directory where the zip folder will be saved.
    :type context: Path
    :param version: Plugin version
    :type version: str
    """
    build_dir = build(context)
    output_directory.mkdir(parents=True, exist_ok=True)
    zip_path = output_directory / f'{SRC_NAME}.{version}.zip'
    with zipfile.ZipFile(zip_path, "w") as fh:
        _add_to_zip(build_dir, fh, arc_path_base=build_dir.parent)
    typer.echo(f"zip generated at {str(zip_path)!r}")
    return zip_path


@app.command()
def build(
        context: typer.Context,
        output_directory: typing.Optional[Path] = LOCAL_ROOT_DIR / "build" / SRC_NAME,
        clean: bool = True,
        tests: bool = False
) -> Path:
    """ Builds plugin directory for use in QGIS application.
    :param context: Application context
    :type context: typer.Context
    :param output_directory: Build output directory plugin where
            files will be saved.
    :type output_directory: Path
    :param clean: Whether current build directory files should be removed,
            before writing new files.
    :type clean: bool
    :param tests: Flag to indicate whether to include test related files.
    :type tests: bool
    :returns: Build directory path.
    :rtype: Path
    """
    if clean:
        shutil.rmtree(str(output_directory), ignore_errors=True)
    output_directory.mkdir(parents=True, exist_ok=True)
    copy_source_files(output_directory, tests=tests)
    icon_path = copy_icon(output_directory)
    if icon_path is None:
        _log("Could not copy icon", context=context)
    compile_resources(context, output_directory)
    return output_directory


@app.command()
def copy_icon(
        output_directory: typing.Optional[Path] = LOCAL_ROOT_DIR / "build/temp",
) -> Path:
    """ Copies the plugin intended icon to the specified output
        directory.
    :param output_directory: Output directory where the icon will be saved.
    :type output_directory: Path
    :returns: Icon output directory path.
    :rtype: Path
    """

    icon_path = LOCAL_ROOT_DIR / PLUGIN_PACKAGE / ICON_PATH
    if icon_path.is_file():
        target_path = output_directory / icon_path.name
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(icon_path, target_path)
        result = target_path
    else:
        result = None
    return result


@app.command()
def copy_source_files(
        output_directory: typing.Optional[Path] = LOCAL_ROOT_DIR / "build/temp",
        tests: bool = False
):
    """ Copies the plugin source files to the specified output
            directory.
    :param output_directory: Output directory where the icon will be saved.
    :type output_directory: Path
    :param tests: Flag to indicate whether to include test related files.
    :type tests: bool
    """
    output_directory.mkdir(parents=True, exist_ok=True)

    for child in LOCAL_ROOT_DIR.iterdir():
        if child.name == "__pycache__":
            continue
        if (tests and child.name in TEST_FILES) or child.name in PLUGIN_FILES:
            target_path = output_directory / child.name

            if child.is_dir():
                handler = shutil.copytree
                patterns = shutil.ignore_patterns(
                    '*.pyc',
                    'tmp*',
                    '__pycache__',
                    'test*'
                )
                handler = partial(handler, ignore=patterns)

            else:
                handler = shutil.copy
            handler(
                str(child.resolve()),
                str(target_path),

            )


@app.command()
def compile_resources(
        context: typer.Context,
        output_directory: typing.Optional[Path] = LOCAL_ROOT_DIR / "build/temp",
):
    """ Compiles plugin resources using the pyrcc package
    :param context: Application context
    :type context: typer.Context
    :param output_directory: Output directory where the resources will be saved.
    :type output_directory: Path
    """
    resources_path = LOCAL_ROOT_DIR / "resources.qrc"
    target_path = output_directory / "resources.py"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    _log(f"compile_resources target_path: {target_path}", context=context)
    subprocess.run(shlex.split(f"pyrcc5 -o {target_path} {resources_path}"))


def _add_to_zip(
        directory: Path,
        zip_handler: zipfile.ZipFile,
        arc_path_base: Path):
    """ Adds to files inside the passed directory to the zip file.
    :param directory: Directory with files that are to be zipped.
    :type directory: Path
    :param zip_handler: Plugin zip file
    :type zip_handler: ZipFile
    :param arc_path_base: Parent directory of the input files directory.
    :type arc_path_base: Path
    """
    for item in directory.iterdir():
        if item.is_file():
            zip_handler.write(item, arcname=str(
                item.relative_to(arc_path_base)))
        else:
            _add_to_zip(item, zip_handler, arc_path_base)


def _log(
        msg,
        *args,
        context: typing.Optional[typer.Context] = None,
        **kwargs):
    """ Logs the message into the terminal.
    :param msg: Directory with files that are to be zipped.
    :type msg: str
    :param context: Application context
    :type context: typer.Context
    """
    if context is not None:
        context_user_data = context.obj or {}
        verbose = context_user_data.get("verbose", True)
    else:
        verbose = True
    if verbose:
        typer.echo(msg, *args, **kwargs)


def _get_existing_releases(
        context: typing.Optional = None,
) -> typing.List[GithubRelease]:
    """ Gets the existing plugin releases in  available in the Github repository.
    :param context: Application context
    :type context: typer.Context
    :returns: List of github releases
    :rtype: List[GithubRelease]
    """
    base_url = "https://api.github.com/repos/" \
               "GEOSYS/qgis-plugin/releases"
    response = httpx.get(base_url)
    result = []
    if response.status_code == 200:
        payload = response.json()
        for release in payload:
            for asset in release["assets"]:
                if asset.get("content_type") == "application/zip":
                    zip_download_url = asset.get("browser_download_url")
                    break
            else:
                zip_download_url = None
            _log(f"zip_download_url: {zip_download_url}", context=context)
            if zip_download_url is not None:
                result.append(
                    GithubRelease(
                        pre_release=release.get("prerelease", True),
                        tag_name=release.get("tag_name"),
                        url=zip_download_url,
                        published_at=dt.datetime.strptime(
                            release["published_at"], "%Y-%m-%dT%H:%M:%SZ"
                        ),
                    )
                )
    return result


def _get_latest_releases(
        current_releases: typing.List[GithubRelease],
) -> typing.Tuple[
    typing.Optional[GithubRelease],
    typing.Optional[GithubRelease]]:
    """ Searches for the latest plugin releases from the Github plugin releases.
    :param current_releases: Existing plugin releases
     available in the Github repository.
    :type current_releases: list
    :returns: Tuple containing the latest stable and experimental releases
    :rtype: tuple
    """
    latest_experimental = None
    latest_stable = None
    for release in current_releases:
        if release.pre_release:
            if latest_experimental is not None:
                if release.published_at > latest_experimental.published_at:
                    latest_experimental = release
            else:
                latest_experimental = release
        else:
            if latest_stable is not None:
                if release.published_at > latest_stable.published_at:
                    latest_stable = release
            else:
                latest_stable = release
    return latest_stable, latest_experimental


if __name__ == "__main__":
    app()