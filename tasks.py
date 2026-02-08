import fnmatch
import glob
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePath
from tempfile import NamedTemporaryFile, mkstemp

import boto3
import requests
from invoke import Collection, task


# Below is from:
# https://stackoverflow.com/questions/3041986/apt-command-line-interface-like-yes-no-input
def query_yes_no(question, default="yes"):
    """Ask a yes/no question via input() and return answer.

    "question" is a string that is presented to the user.
    "default" is the presumed answer if the user just hits <Enter>.
        It must be "yes" (the default), "no" or None (meaning
        an answer is required of the user).

    The "answer" return value is True for "yes" or False for "no".
    """
    valid = {"yes": True, "y": True, "ye": True, "no": False, "n": False}

    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        sys.stdout.write(question + prompt)
        choice = input().lower()

        if default is not None and choice == "":
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("Please respond with 'yes' or 'no' (or 'y' or 'n').\n")


def get_version(c):
    """
    Get version from setuptools-scm (git tags only - no fallbacks).

    Returns version string derived from git tags using setuptools-scm with guess-next-dev scheme.
    This means commits after a tag will get a version like "2.1.19.dev1" (next minor version).
    Raises RuntimeError with helpful message if version cannot be determined.
    """
    try:
        from setuptools_scm import get_version as scm_get_version

        return scm_get_version(
            root=os.path.dirname(__file__),
            version_scheme="guess-next-dev",
            local_scheme="no-local-version",
        )
    except Exception as e:
        print("ERROR: Unable to determine version from git tags.")
        print("Please ensure:")
        print("  1. setuptools-scm is installed (pip install setuptools-scm)")
        print("  2. You are in a git repository with at least one version tag")
        print("  3. Git tags follow the format 'v2.1.18' or similar")
        raise RuntimeError(f"Version determination failed: {e}")


# Handle long filenames or readonly files on windows, see:
# http://bit.ly/2g58Yxu
def rmtree(top):
    for root, dirs, files in os.walk(top, topdown=False):
        for name in files:
            filename = os.path.join(root, name)
            os.chmod(filename, stat.S_IWUSR)
            try:
                os.remove(filename)
            except PermissionError:
                print(
                    "Permission error: unable to remove {}. Skipping that file.".format(
                        filename
                    )
                )

        for name in dirs:
            try:
                os.rmdir(os.path.join(root, name))
            except OSError:
                print(
                    "Unable to remove directory {}. Skipping removing that folder.".format(
                        os.path.join(root, name)
                    )
                )
    try:
        os.rmdir(top)
    except OSError:
        print(
            "Unable to remove directory {}. Skipping removing that folder.".format(top)
        )


# Function to find and replace in a file
def _replace(file_path, regex, subst):
    # Create temp file
    fh, abs_path = mkstemp()

    if sys.version_info[0] < 3:
        with os.fdopen(fh, "w") as new_file:
            with open(file_path) as old_file:
                for line in old_file:
                    new_file.write(regex.sub(subst, line))
    else:
        with open(fh, "w", encoding="Latin-1") as new_file:
            with open(file_path, encoding="Latin-1") as old_file:
                for line in old_file:
                    new_file.write(regex.sub(subst, line))
    os.remove(file_path)
    shutil.move(abs_path, file_path)


###############################################################################
# Misc development tasks (change version, deploy GEE scripts)
###############################################################################


@task(
    help={
        "modules": "Also set versions for any modules specified in ext_libs.local_modules",
        "gee": "Also set versions for gee scripts",
        "version": "Manually specify a version number (e.g., '2.1.20'). If not provided, version is determined from git tags.",
    }
)
def set_version(c, modules=False, gee=False, version=None):
    """
    Generate _version.py with git information and update metadata.txt.

    By default, version is determined automatically from git tags using setuptools-scm.
    You can manually override this by providing the --version parameter.

    Version behavior based on last digit:
    - Even number (e.g., 2.1.18): Stable release - experimental=False, use tagged versions
    - Odd number (e.g., 2.1.19): Development release - experimental=True, use master branch
    """

    # Get version - either from manual parameter or git tags
    if version:
        version_to_write = version
        print(f"Using manually specified version: {version_to_write}")
    else:
        version_to_write = get_version(c)
        print(f"Using version {version_to_write} from git tags")

    # Extract the last numeric component to determine if even or odd
    # For versions like "2.1.19" or "2.1.18rc1" or "2.1.19.dev115"
    # Strip dev/post/rc suffixes (with or without dot separator)
    version_clean = re.sub(r"(\.?(dev|post|rc).*$)", "", version_to_write)
    version_parts = version_clean.split(".")
    try:
        last_number = int(version_parts[-1])
        is_even_version = (last_number % 2) == 0
    except (ValueError, IndexError):
        # If we can't parse, default to odd (experimental)
        is_even_version = False
        last_number = None

    if is_even_version:
        print(
            f"Even version detected ({last_number}) - Setting experimental=False, using tagged versions"
        )
    else:
        print(
            f"Odd version detected ({last_number}) - Setting experimental=True, using master branch"
        )

    # Always generate _version.py with git information captured at build time
    print("Generating LDMP/_version.py with git information")

    # Get git commit info at build time
    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "--short=8", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        git_sha = "unknown"

    try:
        git_date = subprocess.check_output(
            ["git", "log", "-1", "--format=%ci"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        git_date = "unknown"

    # Parse version tuple
    try:
        version_parts_tuple = version_to_write.replace("rc", ".").split(".")
        version_tuple = tuple(int(p) for p in version_parts_tuple if p.isdigit())
    except Exception:
        version_tuple = (0, 0, 0)

    # Write _version.py with all information
    version_file_path = os.path.join(c.plugin.source_dir, "_version.py")
    with open(version_file_path, "w") as f:
        f.write("# This file is auto-generated at build time\n")
        f.write("# Do not edit this file manually\n")
        f.write(f'__version__ = "{version_to_write}"\n')
        f.write(f"__version_tuple__ = {version_tuple}\n")
        f.write("\n")
        f.write("# Git information captured at build time\n")
        f.write(f'__git_sha__ = "{git_sha}"\n')
        f.write(f'__git_date__ = "{git_date}"\n')

    print(
        f"Successfully generated _version.py with version {version_to_write}, git SHA {git_sha}"
    )

    # Always update metadata.txt with current version from setuptools-scm
    print("Setting version to {} in metadata.txt".format(version_to_write))
    # Match PEP 440 versions including dev/post/rc suffixes
    metadata_regex = re.compile(
        r"^(version=)[0-9]+(\.[0-9]+)+(\.?(dev|post|rc)[0-9]+)*", re.MULTILINE
    )
    _replace(
        os.path.join(c.plugin.source_dir, "metadata.txt"),
        metadata_regex,
        r"\g<1>" + version_to_write,
    )

    # Update experimental flag based on even/odd version
    metadata_experimental_regex = re.compile(
        r"^(experimental=)(True|False)", re.MULTILINE | re.IGNORECASE
    )
    experimental_value = "False" if is_even_version else "True"
    print(f"Setting experimental={experimental_value} in metadata.txt")
    _replace(
        os.path.join(c.plugin.source_dir, "metadata.txt"),
        metadata_experimental_regex,
        r"\g<1>" + experimental_value,
    )

    # Set in Sphinx docs conf.py
    # For the 'version' field, use only the main X.Y.Z version (strip dev/post/rc)
    # For the 'release' field, use the full version with dev/post/rc
    print("Setting version to {} in sphinx conf.py".format(version_to_write))

    # Strip dev/post/rc suffixes for the main version number
    version_main = re.sub(r"\.(dev|post|rc).*$", "", version_to_write)

    # Update 'version' field with just the main version (e.g., "2.1.19")
    sphinx_version_regex = re.compile(
        r'(version = ")[0-9]+([.][0-9]+)+(\.?(dev|post|rc)[0-9]+)*',
        re.IGNORECASE,
    )
    _replace(
        os.path.join(c.sphinx.sourcedir, "conf.py"),
        sphinx_version_regex,
        r"\g<1>" + version_main,
    )

    # Update 'release' field with the full version (e.g., "2.1.19.dev111")
    sphinx_release_regex = re.compile(
        r'(release = ")[0-9]+([.][0-9]+)+(\.?(dev|post|rc)[0-9]+)*',
        re.IGNORECASE,
    )
    _replace(
        os.path.join(c.sphinx.sourcedir, "conf.py"),
        sphinx_release_regex,
        r"\g<1>" + version_to_write,
    )

    # Match trends.earth-algorithms.git and trends.earth-schemas.git with optional @version or #egg
    # This handles:
    #   - git+https://github.com/.../trends.earth-algorithms.git@master
    #   - git+https://github.com/.../trends.earth-algorithms.git
    #   - git+https://github.com/.../trends.earth-algorithms.git#egg=te_algorithms[api]
    requirements_txt_regex = re.compile(
        "((trends.earth-schemas.git)|(trends.earth-algorithms.git))(@[.0-9a-z]*)?(#egg=[a-z_\\[\\]]+)?"
    )

    if gee:
        # For GEE scripts, strip any dev/post/rc suffixes and use only the main version
        # e.g., "2.1.19.dev106" becomes "2.1.19"
        v_gee_clean = re.sub(r"\.(dev|post|rc).*$", "", version_to_write)
        print(
            "Setting version to {} for GEE scripts (from {})".format(
                v_gee_clean, version_to_write
            )
        )

        # For the GEE config files the version can't have a dot, so convert to underscore
        v_gee = v_gee_clean.replace(".", "_")

        gee_id_regex = re.compile('(, )?"id": "[0-9a-z-]*"(, )?')
        gee_script_name_regex = re.compile(
            '("name": "[0-9a-zA-Z -]*)( [0-9]+(_[0-9]+)+)(rc[0-9]*)?"'
        )

        # Set version for GEE scripts
        for subdir, dirs, files in os.walk(c.gee.script_dir):
            for file in files:
                filepath = os.path.join(subdir, file)

                if file == "configuration.json":
                    # Check if version is actually changing before clearing ID
                    import json

                    version_changed = False
                    try:
                        with open(filepath, "r") as f:
                            config_content = f.read()
                            config_data = json.loads(config_content)

                        # Extract current version from the name field
                        current_name = config_data.get("name", "")
                        current_version_match = re.search(
                            r"[0-9]+(_[0-9]+)+", current_name
                        )
                        current_version = (
                            current_version_match.group(0)
                            if current_version_match
                            else None
                        )

                        # Check if version is changing
                        if current_version != v_gee:
                            version_changed = True
                            print(
                                "Setting version to {} in {} (was {})".format(
                                    v_gee_clean, filepath, current_version
                                )
                            )
                        else:
                            print(
                                "Version {} already set in {} - leaving ID unchanged".format(
                                    v_gee_clean, filepath
                                )
                            )
                    except Exception as e:
                        # If we can't read the file, assume version is changing
                        print(
                            "Setting version to {} in {} (unable to check existing version: {})".format(
                                v_gee_clean, filepath, e
                            )
                        )
                        version_changed = True

                    # Update the version string
                    _replace(filepath, gee_script_name_regex, r"\g<1> " + v_gee + '"')

                    # Only clear the ID if the version actually changed
                    if version_changed:
                        _replace(filepath, gee_id_regex, "")
                elif file == "requirements.txt":
                    print("Setting version to {} in {}".format(v_gee_clean, filepath))

                    # Use even/odd version logic:
                    # - Even version (e.g., 2.1.18) → use tagged version in dependencies
                    # - Odd version (e.g., 2.1.19) → use master branch
                    # Note: Group 5 preserves #egg=... suffix if present
                    if is_even_version:
                        # Stable release - use tagged version
                        _replace(
                            filepath,
                            requirements_txt_regex,
                            r"\g<1>@v" + v_gee_clean + r"\g<5>",
                        )
                    else:
                        # Development release - use master branch
                        _replace(filepath, requirements_txt_regex, r"\g<1>@master\g<5>")
                elif file == "__init__.py":
                    print("Setting version to {} in {}".format(v_gee_clean, filepath))
                    init_version_regex = re.compile(
                        r"^(__version__[ ]*=[ ]*[\"'])[0-9]+([.][0-9]+)+(\.?(dev|post|rc)[0-9]+)*"
                    )
                    _replace(filepath, init_version_regex, r"\g<1>" + v_gee_clean)

        # Set in scripts.json (use clean version for GEE scripts)
        print(
            "Setting version to {} in scripts.json".format(
                v_gee_clean if gee else version_to_write
            )
        )
        scripts_regex = re.compile(
            r'("version": ")[0-9]+([-._][0-9]+)+(\.?(dev|post|rc)[0-9]+)*',
            re.IGNORECASE,
        )
        scripts_json_path = os.path.join(c.plugin.source_dir, "data", "scripts.json")
        _replace(
            scripts_json_path,
            scripts_regex,
            r"\g<1>" + (v_gee_clean if gee else version_to_write),
        )

    # Always update BOTH requirements files to keep them in sync
    for requirements_file in ["requirements.txt", "requirements-testing.txt"]:
        print(
            "Setting version to {} in package {}".format(
                version_to_write, requirements_file
            )
        )

        # Use even/odd version logic:
        # - Even version (e.g., 2.1.18) → use tagged version in dependencies
        # - Odd version (e.g., 2.1.19) → use master branch
        # Note: Group 5 preserves #egg=... suffix if present
        if is_even_version:
            # Stable release - use tagged version
            _replace(
                requirements_file,
                requirements_txt_regex,
                r"\g<1>@v" + version_to_write + r"\g<5>",
            )
        else:
            # Development release - use master branch
            _replace(requirements_file, requirements_txt_regex, r"\g<1>@master\g<5>")

    if modules:
        for module in c.plugin.ext_libs.local_modules:
            module_path = Path(module["path"]).parent
            ret = query_yes_no(f"Also set version for {module['name']}?")
            if ret:
                subprocess.check_call(["invoke", "set-version"], cwd=module_path)


@task()
def release_github(c):
    v = get_version(c)

    # Build the plugin zipfile
    print("Building plugin zipfile for release...")
    zipfile_path = zipfile_build(c, clean=True, version=3, tests=False)
    zipfile_name = os.path.basename(zipfile_path)

    print(f"Plugin zipfile created at: {zipfile_path}")

    # Make release
    payload = {
        "tag_name": "v{}".format(v),
        "name": "Version {}".format(v),
        "body": """To install this release, download the LDMP.zip file below and then follow [the instructions for installing a release from Github](https://github.com/ConservationInternational/trends.earth#stable-version-from-zipfile).""",
    }

    print("Creating GitHub release...")
    print(f"Repository: {c.github.repo_owner}/{c.github.repo_name}")
    print(f"API URL: {c.github.api_url}")

    # Verify token is configured
    if not hasattr(c.github, "token") or not c.github.token:
        raise ValueError(
            "GitHub token not found. Please set 'github.token' in your invoke.yaml file.\n"
            "The token needs 'repo' scope to create releases.\n"
            "Create a token at: https://github.com/settings/tokens/new"
        )

    headers = {"Authorization": "token {}".format(c.github.token)}

    # Test authentication first
    auth_test = requests.get("{}/user".format(c.github.api_url), headers=headers)

    if auth_test.status_code == 401:
        raise ValueError(
            "GitHub token authentication failed (401 Unauthorized).\n"
            "Your token may be expired or invalid.\n"
            "Please update 'github.token' in your invoke.yaml file.\n"
            "Create a new token with 'repo' scope at: https://github.com/settings/tokens/new"
        )
    elif auth_test.status_code == 403:
        raise ValueError(
            "GitHub token lacks required permissions (403 Forbidden).\n"
            "Your token needs 'repo' scope to create releases.\n"
            "Update your token at: https://github.com/settings/tokens"
        )

    auth_test.raise_for_status()
    user_data = auth_test.json()
    print(f"Authenticated as: {user_data.get('login', 'unknown')}")

    r = requests.post(
        "{}/repos/{}/{}/releases".format(
            c.github.api_url, c.github.repo_owner, c.github.repo_name
        ),
        json=payload,
        headers=headers,
    )

    if r.status_code == 401:
        raise ValueError(
            "GitHub API authentication failed when creating release.\n"
            "Please verify your token has 'repo' scope."
        )
    elif r.status_code == 404:
        raise ValueError(
            f"Repository not found: {c.github.repo_owner}/{c.github.repo_name}\n"
            "Please verify the repository name and that your token has access to it."
        )

    r.raise_for_status()

    release_data = r.json()
    release_id = release_data["id"]
    upload_url = release_data["upload_url"].replace("{?name,label}", "")

    print(f"Release created with ID: {release_id}")
    print(f"Uploading asset: {zipfile_name}")

    # Upload the zipfile as a release asset
    with open(zipfile_path, "rb") as f:
        asset_data = f.read()

    headers = {
        "Authorization": "token {}".format(c.github.token),
        "Content-Type": "application/zip",
    }

    upload_response = requests.post(
        upload_url, params={"name": zipfile_name}, headers=headers, data=asset_data
    )
    upload_response.raise_for_status()

    print(f"Successfully uploaded {zipfile_name} to release v{v}")
    print(f"Release URL: {release_data['html_url']}")


@task(
    help={
        "modules": "Also set tag for any modules specified in ext_libs.local_modules",
        "version": "Manual version string (e.g., '2.1.20'). If not provided, auto-detect from git tags.",
    }
)
def set_tag(c, modules=False, version=None):
    """
    Create and push a git tag for the current version.

    Args:
        modules: If True, also set tags for te_algorithms and te_schemas
        version: Optional manual version string (e.g., "2.1.20"). If not provided,
                 version is determined automatically from git tags using setuptools-scm.
    """
    if version:
        v = version
        print(f"Using manually specified version: {v}")
    else:
        v = get_version(c)
        print(f"Using version {v} from git tags")

    ret = subprocess.run(
        ["git", "diff-index", "HEAD", "--"], capture_output=True, text=True
    )

    if ret.stdout != "":
        ret = query_yes_no("Uncommitted changes exist in repository. Commit these?")

        if ret:
            ret = subprocess.run(
                ["git", "commit", "-m", "Updating version tags for v{}".format(v)]
            )
            ret.check_returncode()
        else:
            print("Changes not committed - VERSION TAG NOT SET")

    print("Tagging version {} and pushing tag to origin".format(v))
    ret = subprocess.run(
        ["git", "tag", "-l", "v{}".format(v)], capture_output=True, text=True
    )
    ret.check_returncode()

    if "v{}".format(v) in ret.stdout:
        # Try to delete this tag on remote in case it exists there
        ret = subprocess.run(["git", "push", "origin", "--delete", "v{}".format(v)])

        if ret.returncode == 0:
            print("Deleted tag v{} on origin".format(v))
    subprocess.check_call(
        ["git", "tag", "-f", "-a", "v{}".format(v), "-m", "Version {}".format(v)]
    )
    subprocess.check_call(["git", "push", "origin", "v{}".format(v)])

    if modules:
        for module in c.plugin.ext_libs.local_modules:
            module_path = Path(module["path"]).parent
            print(f"Also setting tag for {module['name']}")
            subprocess.check_call(["invoke", "set-tag"], cwd=module_path)


def check_tecli_python_version():
    if sys.version_info[0] < 3:
        print(
            "ERROR: tecli tasks require Python version > 2 (you are running Python version {}.{})".format(
                sys.version_info[0], sys.version_info[1]
            )
        )

        return False
    else:
        return True


@task
def tecli_login(c):
    if not check_tecli_python_version():
        return
    subprocess.check_call([sys.executable, os.path.abspath(c.gee.tecli), "login"])


@task
def tecli_clear(c):
    if not check_tecli_python_version():
        return
    subprocess.check_call([sys.executable, os.path.abspath(c.gee.tecli), "clear"])


@task(help={"key": "GEE key in JSON format (base64 encoded)"})
def tecli_config(c, key):
    if not check_tecli_python_version():
        return
    subprocess.check_call(
        [
            sys.executable,
            os.path.abspath(c.gee.tecli),
            "config",
            "set",
            "EE_SERVICE_ACCOUNT_JSON",
            key,
        ]
    )


@task(help={"script": "Script name", "overwrite": "Overwrite scripts if existing?"})
def tecli_publish(c, script=None, overwrite=False):
    if not check_tecli_python_version():
        return

    if not script and not overwrite:
        ret = query_yes_no(
            "WARNING: this will overwrite all scripts on the server with versions equal to the local "
            "scripts.\nDo you wish to continue?"
        )

        if not ret:
            return

    dirs = next(os.walk(c.gee.script_dir))[1]
    n = 0

    for dir in dirs:
        script_dir = os.path.join(c.gee.script_dir, dir)

        if os.path.exists(os.path.join(script_dir, "configuration.json")) and (
            script is None or script == dir
        ):
            print("Publishing {}...".format(dir))
            subprocess.check_call(
                [
                    sys.executable,
                    os.path.abspath(c.gee.tecli),
                    "publish",
                    "--public=True",
                    "--overwrite=True",
                ],
                cwd=script_dir,
            )
            n += 1

    if script and n == 0:
        print('Script "{}" not found.'.format(script))

    # Updating GEE script IDs in config
    if script:
        subprocess.check_call(["invoke", "update-script-ids", "-s", script])
    else:
        subprocess.check_call(["invoke", "update-script-ids"])


@task
def list_scripts(c):
    """
    List all available GEE scripts (folders with configuration.json).
    """
    if not check_tecli_python_version():
        return

    script_root = c.gee.script_dir
    try:
        dirs = next(os.walk(script_root))[1]
    except StopIteration:
        print(f"Script directory {script_root} not found.")
        return

    available_scripts = []
    for dir in dirs:
        config_path = os.path.join(script_root, dir, "configuration.json")
        if os.path.exists(config_path):
            available_scripts.append(dir)

    if available_scripts:
        print("Available scripts:")
        for name in sorted(available_scripts):
            print(f" - {name}")
    else:
        print("No valid scripts found.")


@task(
    help={
        "script": "Script name",
        "queryParams": "Parameters",
        "payload": "Parameters (as json",
    }
)
def tecli_run(c, script, queryParams=None, payload=None):
    if not check_tecli_python_version():
        return
    dirs = next(os.walk(c.gee.script_dir))[1]
    n = 0
    script_dir = None

    for dir in dirs:
        script_dir = os.path.join(c.gee.script_dir, dir)

        if (
            os.path.exists(os.path.join(script_dir, "configuration.json"))
            and script == dir
        ):
            print("Running {}...".format(dir))

            if queryParams:
                print("Using given query parameters as input to script.")
                subprocess.check_call(
                    [
                        sys.executable,
                        os.path.abspath(c.gee.tecli),
                        "start",
                        "--queryParams={}".format(queryParams),
                    ],
                    cwd=script_dir,
                )
            elif payload:
                print("Using given payload as input to script.")
                subprocess.check_call(
                    [
                        sys.executable,
                        os.path.abspath(c.gee.tecli),
                        "start",
                        "--payload={}".format(os.path.abspath(payload)),
                    ],
                    cwd=script_dir,
                )
            else:
                print("Running script without any input parameters.")
                subprocess.check_call(
                    [sys.executable, os.path.abspath(c.gee.tecli), "start"],
                    cwd=script_dir,
                )

            n += 1

            break

    if script and n == 0:
        print('Script "{}" not found.'.format(script))


@task(help={"script": "Script name"})
def update_script_ids(c, script=None):
    with open(c.gee.scripts_json_file) as fin:
        scripts = json.load(fin)

    dirs = next(os.walk(c.gee.script_dir))[1]
    script_dir = None

    print("Updating script IDs")
    for dir in dirs:
        script_dir = os.path.join(c.gee.script_dir, dir)

        if script:
            if script_dir != script:
                continue

        if os.path.exists(os.path.join(script_dir, "configuration.json")):
            with open(os.path.join(script_dir, "configuration.json")) as fin:
                config = json.load(fin)
            try:
                script_name = re.compile("( [0-9]+(_[0-9]+)+$)").sub("", config["name"])

                # Find location of this script in the list of scripts in the
                # script configuration JSON
                script_index = [
                    index
                    for index, script in enumerate(scripts)
                    if script["name"] == script_name
                ]
                assert len(script_index) <= 1
                script_index = script_index[0]

                try:
                    scripts[script_index]["id"] = config["id"]
                except KeyError:
                    print(f"No id found in config for {script_name}")
                script_version = (
                    re.compile("^[a-zA-Z0-9-]* ")
                    .sub("", config["name"])
                    .replace("_", ".")
                )
                scripts[script_index]["version"] = script_version
            except IndexError:
                print(
                    f"Skipping {script_name} as not found in scripts.json - maybe need to publish?"
                )
    with open(c.gee.scripts_json_file, "w") as f_out:
        json.dump(scripts, f_out, sort_keys=True, indent=4)


@task(help={"script": "Script name"})
def tecli_info(c, script=None):
    if not check_tecli_python_version():
        return
    dirs = next(os.walk(c.gee.script_dir))[1]
    n = 0
    script_dir = None

    for dir in dirs:
        script_dir = os.path.join(c.gee.script_dir, dir)

        if os.path.exists(os.path.join(script_dir, "configuration.json")) and (
            script is None or script == dir
        ):
            print("Checking info on {}...".format(dir))
            subprocess.check_call(
                [sys.executable, os.path.abspath(c.gee.tecli), "info"], cwd=script_dir
            )
            n += 1

    if script and n == 0:
        print('Script "{}" not found.'.format(script))


@task(
    help={
        "script": "Script name",
        "since": "Print logs since (number of hours = default 1)",
    }
)
def tecli_logs(c, script, since=1):
    if not check_tecli_python_version():
        return
    dirs = next(os.walk(c.gee.script_dir))[1]
    n = 0
    script_dir = None

    for dir in dirs:
        script_dir = os.path.join(c.gee.script_dir, dir)

        if (
            os.path.exists(os.path.join(script_dir, "configuration.json"))
            and script == dir
        ):
            print("Checking logs for {}...".format(dir))
            subprocess.check_call(
                [
                    sys.executable,
                    os.path.abspath(c.gee.tecli),
                    "logs",
                    f"--since={since}",
                ],
                cwd=script_dir,
            )
            n += 1

            break

    if script and n == 0:
        print('Script "{}" not found.'.format(script))


###############################################################################
# Setup dependencies and install package
###############################################################################


def not_comments(lines, s, e):
    return [line for line in lines[s:e] if line[0] != "#"]


def read_requirements():
    """Return a list of runtime and list of test requirements"""
    with open("requirements.txt") as f:
        lines = f.readlines()
    lines = [line for line in [line.strip() for line in lines] if line]
    divider = "# test requirements"

    try:
        idx = lines.index(divider)
    except ValueError:
        raise Exception('Expected to find "{}" in requirements.txt'.format(divider))

    return not_comments(lines, 0, idx), not_comments(lines, idx + 1, None)


def _pinned_constraints(requirements):
    pinned = []
    for requirement in requirements:
        req = requirement.strip()
        if not req:
            continue
        if "==" not in req:
            continue
        if any(
            req.startswith(prefix) for prefix in ("git+", "hg+", "svn+", "bzr+", "--")
        ):
            continue
        if " @ " in req:
            continue
        pinned.append(req)
    return pinned


@contextmanager
def _temporary_constraint_file(requirements):
    pinned = _pinned_constraints(requirements)
    if not pinned:
        yield None
        return

    with NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
        handle.write("\n".join(pinned))
        handle.flush()
        path = handle.name

    try:
        yield path
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _safe_remove_folder(rootdir):
    """
    Remove a folder safely, handling symlinks appropriately.

    If the root folder is a symlink: remove only the symlink (preserve the original)
    If the root folder is not a symlink: remove the entire folder and all its contents

    Needed on windows to avoid removing the original files linked to within
    each folder
    """
    rootdir = Path(rootdir)
    if rootdir.is_symlink():
        # If the root directory itself is a symlink, just remove the symlink
        rootdir.rmdir()
        print(f"Removed symlinked directory: {rootdir}")
    else:
        # Not a symlink, so remove the entire directory tree
        shutil.rmtree(rootdir)
        print(f"Removed directory and all contents: {rootdir}")


@task(
    help={
        "clean": "Clean out dependencies first",
        "link": "Symlink dependendencies to their local repos",
        "pip": 'Path to pip (usually "pip" or "pip3"',
    }
)
def plugin_setup(c, clean=True, link=False, pip="pip"):
    """install dependencies"""
    ext_libs = os.path.abspath(c.plugin.ext_libs.path)

    if clean and os.path.exists(ext_libs):
        _safe_remove_folder(ext_libs)

    if sys.version_info[0] < 3:
        if not os.path.exists(ext_libs):
            os.makedirs(ext_libs)
    else:
        os.makedirs(ext_libs, exist_ok=True)
    runtime, test = read_requirements()

    os.environ["PYTHONPATH"] = ext_libs

    all_requirements = runtime + test

    with _temporary_constraint_file(all_requirements) as constraint_path:
        constraint_args = []
        if constraint_path:
            constraint_args = ["--constraint", constraint_path]

        # Separate git packages from regular packages
        git_packages = []
        regular_packages = []

        for req in all_requirements:
            req_stripped = req.strip()
            # Check for git packages in various formats
            if (
                req_stripped.startswith(("git+", "hg+", "svn+", "bzr+"))
                or " @ git+" in req_stripped
                or " @ hg+" in req_stripped
                or " @ svn+" in req_stripped
                or " @ bzr+" in req_stripped
            ):
                git_packages.append(req)
                print(f"Detected git package: {req}")
            else:
                regular_packages.append(req)
                print(f"Detected regular package: {req}")

        print(f"Found {len(git_packages)} git packages: {git_packages}")
        print(f"Found {len(regular_packages)} regular packages: {regular_packages}")

        # Install regular packages directly to ext_libs
        for req in regular_packages:
            # Don't install numpy with pyqtgraph as QGIS already has numpy. So use
            # the --no-deps flag (-N for short) with that package only.
            if "pyqtgraph" in req:
                cmd = [
                    pip,
                    "install",
                    "--upgrade",
                    "--no-cache-dir",
                    "--no-deps",
                    "-t",
                    ext_libs,
                ]
                cmd.extend(constraint_args)
                cmd.append(req)
                subprocess.check_call(cmd)
            else:
                cmd = [
                    pip,
                    "install",
                    "--upgrade",
                    "--no-cache-dir",
                    "-t",
                    ext_libs,
                ]
                cmd.extend(constraint_args)
                cmd.append(req)
                subprocess.check_call(cmd)

        # Install git packages to temporary location, then copy to ext_libs
        if git_packages:
            import tempfile

            # Extract expected package names from git packages
            git_package_names = []
            for req in git_packages:
                # Extract package name from "package_name @ git+url" format
                if " @ " in req:
                    package_name = req.split(" @ ")[0].strip()
                else:
                    # For direct git+url format, extract from URL
                    package_name = (
                        req.split("/")[-1].replace(".git", "").replace("git+", "")
                    )
                git_package_names.append(package_name)

            print(f"Expected git package names: {git_package_names}")

            with tempfile.TemporaryDirectory() as temp_dir:
                print(f"Installing git packages to temporary directory: {temp_dir}")
                for req in git_packages:
                    print(f"Installing git package: {req}")
                    # Convert PEP 508 @ syntax to direct git+ URL for better compatibility with --target
                    if " @ " in req:
                        # Extract the git URL from "package @ git+url" format
                        git_url = req.split(" @ ")[1]
                        install_req = git_url
                    else:
                        install_req = req

                    print(f"Using install requirement: {install_req}")
                    # Install git packages using direct git+ URL to temp directory
                    cmd = [
                        pip,
                        "install",
                        "--upgrade",
                        "--no-cache-dir",
                        "--target",
                        temp_dir,
                    ]
                    cmd.extend(constraint_args)
                    cmd.append(install_req)
                    subprocess.check_call(cmd)

                # Copy all packages from temp directory to ext_libs (git packages + their dependencies)
                print(f"Contents of temp directory: {os.listdir(temp_dir)}")
                for item in os.listdir(temp_dir):
                    src_path = os.path.join(temp_dir, item)
                    dst_path = os.path.join(ext_libs, item)

                    # Check if this is one of our expected git packages
                    is_git_package = any(
                        item == pkg_name
                        or item == pkg_name.replace("_", "-")
                        or item == pkg_name.replace("-", "_")
                        for pkg_name in git_package_names
                    )

                    print(f"Checking item '{item}': git_package={is_git_package}")

                    if os.path.isdir(src_path):
                        # Skip dist-info directories and other metadata
                        if not item.endswith(
                            (".dist-info", ".egg-info", "__pycache__")
                        ):
                            # Check if this package already exists in ext_libs (from regular package installation)
                            if os.path.exists(dst_path):
                                if is_git_package:
                                    # For git packages, replace the existing version
                                    print(
                                        f"Replacing existing package {item} with git version"
                                    )
                                    shutil.rmtree(dst_path)
                                    shutil.copytree(src_path, dst_path)
                                    print(f"Copied git package {item} to ext_libs")
                                else:
                                    # For dependencies, only copy if not already installed via regular packages
                                    print(
                                        f"Dependency {item} already exists in ext_libs, skipping"
                                    )
                            else:
                                # Package doesn't exist in ext_libs, copy it
                                shutil.copytree(src_path, dst_path)
                                if is_git_package:
                                    print(f"Copied git package {item} to ext_libs")
                                else:
                                    print(
                                        f"Copied git package dependency {item} to ext_libs"
                                    )
                        else:
                            print(f"Skipping metadata directory: {item}")
                    else:
                        # Copy individual files if needed
                        if not item.startswith(".") and not item.endswith(".pyc"):
                            if not os.path.exists(dst_path):
                                shutil.copy2(src_path, dst_path)
                                print(f"Copied file {item} to ext_libs")

                print(
                    "Git package installation completed. Dependencies were included with the packages."
                )

    # Remove the .pyc files as these are no allowed on QGIS repo
    pyc_files = Path(ext_libs).rglob("*.pyc")
    for pyc in pyc_files:
        pyc.unlink()

    if link:
        for module in c.plugin.ext_libs.local_modules:
            ln = os.path.abspath(c.plugin.ext_libs.path) + os.path.sep + module["name"]
            target_path = module["path"]

            # Validate that the target path exists
            if not os.path.exists(target_path):
                raise ValueError(
                    f"Symlink target path does not exist: {target_path}\n"
                    f"Check your invoke.yaml configuration for local_modules.\n"
                    f"Expected to find module '{module['name']}' at: {target_path}"
                )

            if os.path.islink(ln):
                existing_target = os.readlink(ln)
                # Check if existing symlink points to a valid location
                if not os.path.exists(ln):
                    print(
                        f"WARNING: Existing symlink {ln} is broken "
                        f"(points to non-existent: {existing_target})"
                    )
                    print(
                        f"Removing broken symlink and creating new one to {target_path}"
                    )
                    os.remove(ln)
                    os.symlink(target_path, ln)
                elif existing_target != target_path:
                    print(
                        f"WARNING: Symlink {ln} points to {existing_target} "
                        f"but config specifies {target_path}"
                    )
                    print(f"Updating symlink to point to {target_path}")
                    os.remove(ln)
                    os.symlink(target_path, ln)
                else:
                    print(f"{ln} is already correctly linked to {existing_target}")
            else:
                print(
                    "Linking local repo of {} to plugin ext_libs".format(module["name"])
                )
                if os.path.exists(ln):
                    shutil.rmtree(ln)
                os.symlink(target_path, ln)


@task(
    help={
        "clean": "remove existing install folder first",
        "version": "what version of QGIS to install to",
        "profile": "what profile to install to (only applies to QGIS3",
        "fast": "Deprecated parameter (previously used for numba compilation)",
        "link": "Symlink folder to QGIS profile directory",
    }
)
def plugin_install(
    c, clean=False, version=3, profile="default", fast=False, link=False
):
    """install plugin to qgis"""
    set_version(c)
    plugin_name = c.plugin.name
    src = os.path.join(os.path.dirname(__file__), plugin_name)

    if version == 2:
        folder = ".qgis2"
    elif version == 3:
        if platform.system() == "Darwin":
            folder = "Library/Application Support/QGIS/QGIS3/profiles/"

        if platform.system() == "Linux":
            folder = ".local/share/QGIS/QGIS3/profiles/"

        if platform.system() == "Windows":
            folder = "AppData\\Roaming\\QGIS\\QGIS3\\profiles\\"
        folder = os.path.join(folder, profile)
    else:
        print("ERROR: unknown qgis version {}".format(version))

        return

    dst_plugins = os.path.join(os.path.expanduser("~"), folder, "python", "plugins")
    dst_this_plugin = os.path.join(dst_plugins, plugin_name)
    src = os.path.abspath(src)
    dst_this_plugin = os.path.abspath(dst_this_plugin)

    if not hasattr(os, "symlink") or not link:
        if clean and os.path.exists(dst_this_plugin):
            print(f"Removing folder {dst_this_plugin}")
            _safe_remove_folder(dst_this_plugin)

        print(
            "Copying plugin to QGIS version {} plugin folder at {}".format(
                version, dst_this_plugin
            )
        )
        for root, dirs, files in os.walk(src):
            relpath = os.path.relpath(root)

            if not os.path.exists(os.path.join(dst_plugins, relpath)):
                os.makedirs(os.path.join(dst_plugins, relpath))

            for f in _filter_excludes(root, files, c):
                try:
                    shutil.copy(
                        os.path.join(root, f), os.path.join(dst_plugins, relpath, f)
                    )
                except PermissionError:
                    print(
                        "Permission error: unable to copy {} to {}. Skipping that file.".format(
                            f, os.path.join(dst_plugins, relpath, f)
                        )
                    )
            _filter_excludes(root, dirs, c)
    else:
        if clean and os.path.exists(dst_this_plugin):
            print(f"Removing folder {dst_this_plugin}")
            _safe_remove_folder(dst_this_plugin)

        if os.path.exists(dst_this_plugin):
            print(
                f"Not linking - plugin folder for QGIS version {version} already "
                f"exists at {dst_this_plugin}. Use '-c' to clean that folder if "
                "desired."
            )
        else:
            print(
                "Linking plugin development folder to QGIS version {} plugin folder at {}".format(
                    version, dst_this_plugin
                )
            )
            os.symlink(src, dst_this_plugin)


def file_changed(infile, outfile):
    try:
        infile_s = os.stat(infile)
        outfile_s = os.stat(outfile)

        return infile_s.st_mtime > outfile_s.st_mtime
    except Exception:
        return True


def _filter_excludes(root, items, c):
    excludes = set(c.plugin.excludes)
    skips = c.plugin.skip_exclude

    def exclude(p):
        any([fnmatch.fnmatch(p, e) for e in excludes])

    if not items:
        return []

    # to prevent descending into dirs, modify the list in place

    for item in list(items):  # copy list or iteration values change
        itempath = os.path.join(os.path.relpath(root), item)

        if exclude(itempath) and item not in skips:
            # debug('Excluding {}'.format(itempath))
            items.remove(item)

    return items


# Compile all ui and resource files - only used on CI so that gui can be loaded
# on docker image
@task(
    help={
        "clean": "remove existing install folder first",
    }
)
def compile_files(c, clean=False):
    pyrcc = "pyrcc5"
    pyrcc_path = check_path(pyrcc)

    if not pyrcc:
        print(
            "ERROR: {} is not in your path---unable to compile resource file(s)".format(
                pyrcc
            )
        )
        return
    else:
        res_files = c.plugin.resource_files
        res_count = 0
        skip_count = 0
        for res in res_files:
            if os.path.exists(res):
                (base, ext) = os.path.splitext(res)
                output = "{}.py".format(base)
                if clean or file_changed(res, output):
                    print("Compiling {} to {}".format(res, output))
                    subprocess.check_call([pyrcc_path, "-o", output, res])
                    res_count += 1
                else:
                    skip_count += 1
            else:
                print("{} does not exist---skipped".format(res))
        print("Compiled {} resource files. Skipped {}.".format(res_count, skip_count))


# Below is based on pb_tool:
# https://github.com/g-sherman/plugin_build_tool
def check_path(app):
    """Adapted from StackExchange:
    http://stackoverflow.com/questions/377017
    """

    def is_exe(fpath):
        return os.path.exists(fpath) and os.access(fpath, os.X_OK)

    def ext_candidates(fpath):
        yield fpath

        for ext in os.environ.get("PATHEXT", "").split(os.pathsep):
            yield fpath + ext

    # Also look in folders under this python versions lib path
    folders = os.environ["PATH"].split(os.pathsep)
    folders.extend(
        [x[0] for x in os.walk(os.path.join(os.path.dirname(sys.executable), "Lib"))]
    )
    fpath, fname = os.path.split(app)

    if fpath:
        if is_exe(app):
            return app
    else:
        for path in folders:
            exe_file = os.path.join(path, app)

            for candidate in ext_candidates(exe_file):
                if is_exe(candidate):
                    return candidate

    return None


###############################################################################
# Translation
###############################################################################


@task
def lrelease(c):
    print("Releasing translations using lrelease...")
    lrelease = check_path("lrelease")

    if not lrelease:
        print(
            "ERROR: lrelease is not in your path---unable to release translation files"
        )

        return

    for translation in c.plugin.translations:
        subprocess.check_call(
            [
                lrelease,
                os.path.join(c.plugin.i18n_dir, "LDMP_{}.ts".format(translation)),
            ]
        )


@task(
    help={
        "force": "Force the download of the translations files regardless of whether "
        "timestamps on the local computer are newer than those on the server"
    }
)
def translate_pull(c, force=False):
    print("Pulling transifex translations...")

    if force:
        subprocess.check_call([c.sphinx.tx_path, "pull", "-f"])
    else:
        subprocess.check_call([c.sphinx.tx_path, "pull"])

    lrelease(c)


# @task
# def translate_update_resources(c):
#     print("Updating transifex...")
#     subprocess.check_call("sphinx-intl update-txconfig-resources --pot-dir {docroot}/i18n/pot --transifex-project-name {transifex_name}".format(docroot=c.sphinx.docroot, transifex_name=c.sphinx.transifex_name))
#


@task(
    help={
        "force": "Push source files to transifex without checking modification times",
        "version": "what version of QGIS to install to",
    }
)
def translate_push(c, force=False, version=3):
    print("Building changelog...")
    changelog_build(c)

    print("Building download page...")
    build_download_page(c)

    # Below is necessary just to avoid warning messages regarding missing image
    # files when Sphinx is used later on
    print("Localizing resources...")
    localize_resources(c, "en")

    print("Gathering strings...")
    gettext(c)
    print("Generating the pot files for the LDMP toolbox help files...")

    for translation in c.plugin.translations:
        subprocess.check_call(
            c.sphinx.sphinx_intl.split()
            + [
                "--config",
                f"{c.sphinx.sourcedir}/conf.py",
                "update",
                "-p",
                f"{c.sphinx.docroot}/i18n/pot",
                "-l",
                f"{translation}",
            ]
        )

    print("Gathering strings for translation using pylupdate...")

    if version == 2:
        pylupdate = "pylupdate4"
    elif version == 3:
        pylupdate = "pylupdate5"
    else:
        print("ERROR: unknown qgis version {}".format(version))

        return
    pylupdate = check_path(pylupdate)

    if not pylupdate:
        print(
            "ERROR: pylupdate4/pylupdate5 is not in your path---unable to gather strings for translation"
        )

        return
    else:
        subprocess.check_call(
            [pylupdate, os.path.join(c.plugin.i18n_dir, "i18n.pro"), "-noobsolete"]
        )

    if force:
        subprocess.check_call([c.sphinx.tx_path, "push", "-f", "-s"])
    else:
        subprocess.check_call([c.sphinx.tx_path, "push", "-s"])


@task(help={"language": "language"})
def gettext(c, language=None):
    if not language:
        language = c.sphinx.base_language
    script_folder = str(Path(__file__).parent)
    SPHINX_OPTS = (
        f"-t language_{language} -A language={language} "
        f"{script_folder}/{c.sphinx.sourcedir}"
    )
    I18N_SPHINX_OPTS = f"{SPHINX_OPTS} {script_folder}/{c.sphinx.docroot}/i18n/pot"

    subprocess.check_call(
        c.sphinx.sphinx_build.split()
        + ["-b", "gettext", "-a"]
        + I18N_SPHINX_OPTS.split()
    )


###############################################################################
# Build documentation
###############################################################################


@task(
    help={
        "ignore_errors": "ignore documentation errors",
        "language": "which language to build (all are built by default)",
        "fast": "only check english docs",
    }
)
def docs_spellcheck(c, ignore_errors=False, language=None, fast=False):
    if language:
        languages = [language]
    else:
        languages = [c.sphinx.base_language]
        languages.extend(c.plugin.translations)

    for language in languages:
        print(f"\nBuilding {language} documentation...")
        SPHINX_OPTS = (
            f"-t language_{language} -A language={language} {c.sphinx.sourcedir}"
        )

        if language != "en" or ignore_errors:
            subprocess.check_call(
                c.sphinx.sphinx_intl.split()
                + ["-b", "spelling", "-a"]
                + SPHINX_OPTS.split()
                + [f"{c.sphinx.builddir}/html/{language}"]
            )
        else:
            subprocess.check_call(
                c.sphinx.sphinx_build.split()
                + ["-n", "-W", "-b", "spelling", "-a"]
                + SPHINX_OPTS.split()
                + [f"{c.sphinx.builddir}/html/{language}"]
            )

        if fast:
            break


@task(
    help={
        "clean": "clean out built artifacts first",
        "ignore_errors": "ignore documentation errors",
        "language": "which language to build (all are built by default)",
        "fast": "only build english html docs",
        "pdf": "build pdf docs",
        "upload": "upload pdfs of docs to S3",
    }
)
def docs_build(
    c,
    clean=False,
    ignore_errors=False,
    language=None,
    fast=False,
    pdf=False,
    upload=False,
):
    if clean:
        rmtree(c.sphinx.builddir)

    if language:
        languages = [language]
    else:
        languages = [c.sphinx.base_language]
        languages.extend(c.plugin.translations)

    if fast:
        pdf = False
        languages = ["en"]

    print("\nBuilding changelog...")
    changelog_build(c)

    print("\nBuilding download page...")
    build_download_page(c)

    client = _get_s3_client()

    for language in languages:
        print(f"\nBuilding {language} documentation...")
        SPHINX_OPTS = (
            f"-t language_{language} -A language={language} {c.sphinx.sourcedir}"
        )

        print(f"\nLocalizing resources for {language} documentation...")

        localize_resources(c, language)

        subprocess.check_call(
            c.sphinx.sphinx_intl.split()
            + [
                "--config",
                f"{c.sphinx.sourcedir}/conf.py",
                "build",
                f"--language={language}",
            ]
        )

        if language != "en" or ignore_errors:
            subprocess.check_call(
                c.sphinx.sphinx_build.split()
                + ["-b", "html", "-a"]
                + SPHINX_OPTS.split()
                + [f"{c.sphinx.builddir}/html/{language}"]
            )
        else:
            subprocess.check_call(
                c.sphinx.sphinx_build.split()
                + ["-n", "-W", "-b", "html", "-a"]
                + SPHINX_OPTS.split()
                + [f"{c.sphinx.builddir}/html/{language}"]
            )
        print(
            f"HTML Build finished. The HTML pages for '{language}' "
            f"are in {c.sphinx.builddir}/html/{language}."
        )

        if pdf:
            # Build PDF using rst2pdf (produces PDF directly without LaTeX)
            pdf_dir = f"{c.sphinx.builddir}/pdf/{language}"
            subprocess.check_call(
                c.sphinx.sphinx_build.split()
                + ["-b", "pdf", "-a"]
                + SPHINX_OPTS.split()
                + [f"{pdf_dir}"]
            )

            out_dir = f"{c.sphinx.builddir}/html/{language}/pdfs"

            if not os.path.exists(out_dir):
                os.makedirs(out_dir)

            pdf_files = [
                Path(pdf_file).name for pdf_file in glob.glob(f"{pdf_dir}/*.pdf")
            ]

            for pdf_file in pdf_files:
                shutil.move(f"{pdf_dir}/{pdf_file}", f"{out_dir}/{pdf_file}")

                if upload:
                    with open(f"{out_dir}/{pdf_file}", "rb") as data:
                        key = f"documentation/{pdf_file}"
                        client.put_object(
                            Key=key,
                            Body=data,
                            Bucket=c.sphinx.documentation_deploy_s3_bucket,
                        )
                        client.put_object_acl(
                            ACL="public-read",
                            Key=key,
                            Bucket=c.sphinx.documentation_deploy_s3_bucket,
                        )
                    print(f"{pdf_file} uploaded to S3")

            print(
                f"PDF Build finished. The PDF pages for '{language}' are in {out_dir}."
            )


def localize_resources(c, language=None):
    if language is None:
        language = c.sphinx.base_language

    print(
        "Removing all static content from {sourcedir}/static.".format(
            sourcedir=c.sphinx.sourcedir
        )
    )

    if os.path.exists("{sourcedir}/static".format(sourcedir=c.sphinx.sourcedir)):
        rmtree("{sourcedir}/static".format(sourcedir=c.sphinx.sourcedir))
    print(
        "Copy 'en' (base) static content to {sourcedir}/static.".format(
            sourcedir=c.sphinx.sourcedir
        )
    )

    if os.path.exists("{resourcedir}/en".format(resourcedir=c.sphinx.resourcedir)):
        shutil.copytree(
            "{resourcedir}/en".format(resourcedir=c.sphinx.resourcedir),
            "{sourcedir}/static".format(sourcedir=c.sphinx.sourcedir),
        )
    print(
        "Copy localized '{lang}' static content to {sourcedir}/static.".format(
            lang=language, sourcedir=c.sphinx.sourcedir
        )
    )

    if language != "en" and os.path.exists(
        "{resourcedir}/{lang}".format(resourcedir=c.sphinx.resourcedir, lang=language)
    ):
        src = "{resourcedir}/{lang}".format(
            resourcedir=c.sphinx.resourcedir, lang=language
        )
        dst = "{sourcedir}/static".format(sourcedir=c.sphinx.sourcedir)

        for item in os.listdir(src):
            s = os.path.join(src, item)
            d = os.path.join(dst, item)

            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)


def check_docs_image_ext(c):
    """
    Check the capitalization of *.png images for docs. They should be in
    lowercase otherwise they will be skipped from the build process as Linux
    is case-sensitive w.r.t. file extensions.
    """
    res_dir = c.sphinx.resourcedir
    if not os.path.exists(res_dir):
        print("doc's resource directory does not exist. Unable to browse image files.")
        return

    for p in Path(res_dir).rglob("*.PNG"):
        if p.suffix.isupper():
            np = Path(f"{p.with_suffix('').as_posix()}.png")
            os.rename(p.as_posix(), np.as_posix())


@task
def rtd_pre_build(c):
    """
    Checks capitalization and copies docs resources based on language
    prior to build in RTD.
    """
    print("Checking case of image extensions...")
    check_docs_image_ext(c)
    print("Copying docs resources based on language...")
    localize_resources(c)
    if os.environ.get("READTHEDOCS_PROJECT") == "trends.earth" and os.environ.get(
        "READTHEDOCS_VERSION_TYPE"
    ) in ["branch", "tag"]:
        print("Building download page...")
        build_download_page(c)
    print("Building changelog...")
    changelog_build(c)


@task
def changelog_build(c):
    out_txt = [
        "Changelog\n",
        "======================\n",
        "\n",
        "This page lists the version history of |trends.earth|.\n",
    ]

    with open(os.path.join(c.plugin.source_dir, "metadata.txt")) as fin:
        metadata = fin.readlines()

    changelog_header_re = re.compile("^changelog=", re.IGNORECASE)
    version_header_re = re.compile(
        r"^[ ]*[0-9]+(\.[0-9]+){1,2}(rc[0-9]*)?", re.IGNORECASE
    )

    at_changelog = False

    for line in metadata:
        if not at_changelog and not changelog_header_re.match(line):
            continue
        elif changelog_header_re.match(line):
            line = changelog_header_re.sub("  ", line)
            at_changelog = True
        version_header = version_header_re.match(line)

        if version_header:
            version_number = version_header.group(0)
            version_number = version_number.strip(" \n")
            line = line.strip(" \n")
            line = "\n`{} <https://github.com/ConservationInternational/trends.earth/releases/tag/v{}>`_\n".format(
                line, version_number
            )
            line = [
                line,
                "-----------------------------------------------------------------------------------------------------------------------------\n\n",
            ]
        out_txt.extend(line)

    out_file = "{docroot}/source/for_developers/changelog.rst".format(
        docroot=c.sphinx.docroot
    )
    with open(out_file, "w") as fout:
        metadata = fout.writelines(out_txt)


def _load_country_names():
    """Load country names from boundaries list JSON file."""
    boundaries_file = os.path.join(
        os.path.dirname(__file__), "LDMP", "data", "boundaries_list_gbOpen.json"
    )
    try:
        with open(boundaries_file, "r", encoding="utf-8") as f:
            boundaries_data = json.load(f)

        # Create a mapping from ISO code to country name
        iso_to_name = {}
        for country in boundaries_data.get("data", []):
            iso_code = country.get("boundaryISO")
            country_name = country.get("boundaryName")
            if iso_code and country_name:
                iso_to_name[iso_code] = country_name

        return iso_to_name
    except Exception as e:
        print(f"Warning: Could not load country names from boundaries list: {e}")
        return {}


def _get_country_display_name(iso_code, country_names):
    """Get display name for country as 'Country Name (ISO)' or just 'ISO' if name not found."""
    country_name = country_names.get(iso_code)
    if country_name:
        return f"{country_name} ({iso_code})"
    else:
        return iso_code


def _make_download_link(c, title, key, data):
    filename = data.get(key, "")
    if filename:
        return (
            f"[{title}]"
            f"(https://{c.data_downloads.s3_bucket}/"
            f"{c.data_downloads.s3_prefix}{filename})"
        )
    else:
        return ""


def _make_sdg_download_row(c, iso, data, country_names):
    display_name = _get_country_display_name(iso, country_names)
    return (
        f"| {display_name} | "
        + f"{_make_download_link(c, f'{iso} (Trends.Earth LPD)', 'TrendsEarth-LPD-5', data)} | "
        + f"{_make_download_link(c, f'{iso} (FAO-WOCAT LPD)', 'FAO-WOCAT-LPD-5', data)} | "
        + f"{_make_download_link(c, f'{iso} (JRC LPD)', 'JRC-LPD-5', data)} |\n"
    )


def _make_drought_download_row(c, iso, data, country_names):
    display_name = _get_country_display_name(iso, country_names)
    return (
        f"| {display_name} | "
        + f"{_make_download_link(c, f'{iso} (UK-CEH)', 'Drought-UK-CEH', data)} | "
        + f"{_make_download_link(c, f'{iso} (CHIRPS)', 'Drought-CHIRPS', data)} |\n"
    )


@task
def build_download_page(c):
    out_txt = """# Downloads

This page lists data packages containing national-level datasets (produced by Trends.Earth),
following accepted best practices for calculating the UNCCD Indicators for [land degradation](#sdg-indicator-1531-unccd-strategic-objectives-1-and-2)
and [drought vulnerability and exposure](#drought-hazard-vulnerability-and-exposure-unccd-strategic-objective-3).

These zipfiles are designed to be imported directly into Trends.Earth, and may be useful to countries
reporting to the UNCCD on Strategic Objectives 1, 2, and 3 (including SDG Indicator 15.3.1). Global datasets
are also available as Cloud-optimized GeoTIFFs (COGs) and as Google Earth Engine assets. See the
[Trends.Earth SDG Indicator 15.3.1 Datasets page on Zenodo](https://doi.org/10.5281/zenodo.16573473) for
more details on these datasets.

The methods used to produce the estimates of land degradation in these files are consistent with [Version 2.0 of the Good Practice Guidance for SDG Indicator 15.3.1](https://www.unccd.int/resources/manuals-and-guides/good-practice-guidance-sdg-indicator-1531-proportion-land-degraded). Calculations of land condition are consistent with the [addendum to that guidance](https://www.unccd.int/resources/manuals-and-guides/addendum-good-practice-guidance-sdg-indicator-1531-proportion-land). Calculations of drought vulnerability and exposure are consistent with the [Good Practice Guidance for National Reporting on UNCCD Strategic Objective 3](https://www.unccd.int/resources/manuals-and-guides/good-practice-guidance-national-reporting-unccd-strategic-objective-3).

**This site and the products of Trends.Earth are made available under the terms of the
Creative Commons Attribution 4.0 International License [(CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/). The boundaries and
names used, and the designations used, do not imply official endorsement or acceptance
by Conservation International Foundation, or its partner organizations and
contributors.**

The below packages use data from [geoBoundaries](https://www.geoboundaries.org/) to define
country borders. These boundaries are made available by geoBoundaries under the
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) license.

(sdg-indicator-1531-unccd-strategic-objectives-1-and-2)=
## SDG Indicator 15.3.1 (UNCCD Strategic Objectives 1 and 2)

The below datasets can be used to support assessing SDG Indicator 15.3.1, and include
indicators of change in land productivity dynamics (LPD), land cover, and soil organic
carbon. These datasets can be used to support reporting on UNCCD Strategic Objectives 1
and 2. Note that there are three different LPD datasets available (from
the default Trends.Earth method, from FAO-WOCAT, and from JRC).

| Country | SDG 15.3.1 using Trends.Earth LPD | SDG 15.3.1 using FAO-WOCAT LPD | SDG 15.3.1 using JRC LPD |
|---------|---------|--------------------|---------------|
"""

    # Load country names from boundaries list
    country_names = _load_country_names()

    client = _get_s3_client()

    paginator = client.get_paginator("list_objects_v2")
    objects = []

    for page in paginator.paginate(
        Bucket=c.data_downloads.s3_bucket, Prefix=c.data_downloads.s3_prefix
    ):
        objects.extend(page.get("Contents", []))

    sdg_links = {}
    for item in objects:
        if item["Key"] == c.data_downloads.s3_prefix:
            # Skip the key that is just the parent folder itself
            continue
        filename = PurePath(item["Key"]).name
        iso = re.match("[A-Z]{3}", filename)[0]

        if iso not in sdg_links:
            sdg_links[iso] = {}

        if re.search("SDG15_JRC-LPD-5", filename):
            sdg_links[iso]["JRC-LPD-5"] = filename
        elif re.search("SDG15_TrendsEarth-LPD-5", filename):
            sdg_links[iso]["TrendsEarth-LPD-5"] = filename
        elif re.search("SDG15_FAO-WOCAT-LPD-5", filename):
            sdg_links[iso]["FAO-WOCAT-LPD-5"] = filename
        else:
            continue

    # Sort by country name instead of ISO code
    sorted_isos = sorted(sdg_links.keys(), key=lambda iso: country_names.get(iso, iso))
    for iso in sorted_isos:
        values = sdg_links[iso]
        if values == {}:
            # Skip empty entries
            continue
        out_txt += _make_sdg_download_row(c, iso, values, country_names)

    out_txt += """

(drought-hazard-vulnerability-and-exposure-unccd-strategic-objective-3)=
## Drought hazard, vulnerability and exposure (UNCCD Strategic Objective 3)

The below datasets can be used to support assessing drought hazard, vulnerability, and
exposure, and for reporting on UNCCD Strategic Objective 3.

These data are processed in accordance with the [Good Practice Guidance for National Reporting on UNCCD Strategic Objective 3](https://www.unccd.int/resources/manuals-and-guides/good-practice-guidance-national-reporting-unccd-strategic-objective-3). Two variations of the data are provided. Both are based on the Standardized Precipitation Index (SPI) for a 12-month accumulation period. One version uses the [Global Multi-Index Drought (GMID) dataset from the UK-CEH](https://eidc.ac.uk/), the other uses an SPI dataset derived by the Trends.Earth team from the [CHIRPS](https://www.chc.ucsb.edu/data/chirps) precipitation dataset.

 CHIRPS is a gridded precipitation dataset spanning 50°S-50°N, starting in 1981, that merges in-situ with satellite data to produce a timeseries grid.
 

| Country | Drought indicators (UK-CEH SPI) | Drought indicators (CHIRPS SPI) |
|---------|----------------------------------|----------------------------------|
"""

    drought_links = {}
    for item in objects:
        if item["Key"] == c.data_downloads.s3_prefix:
            # Skip the key that is just the parent folder itself
            continue
        filename = PurePath(item["Key"]).name
        iso = re.match("[A-Z]{3}", filename)[0]

        if iso not in drought_links:
            drought_links[iso] = {}

        if re.search("Drought_SPI-12-CHIRPS", filename) or re.search(
            "Drought.*SPI-12-CHIRPS", filename
        ):
            drought_links[iso]["Drought-CHIRPS"] = filename
        elif re.search("Drought_SPI-12-UKCEH", filename) or re.search(
            "Drought.*SPI-12-UKCEH", filename
        ):
            drought_links[iso]["Drought-UK-CEH"] = filename
        elif re.search("Drought", filename):
            # Default drought files without SPI suffix are UK-CEH (legacy)
            drought_links[iso]["Drought-UK-CEH"] = filename
        else:
            continue

    # Sort by country name instead of ISO code
    sorted_isos = sorted(
        drought_links.keys(), key=lambda iso: country_names.get(iso, iso)
    )
    for iso in sorted_isos:
        values = drought_links[iso]
        if values == {}:
            # Skip empty entries
            continue
        out_txt += _make_drought_download_row(c, iso, values, country_names)

    with open(
        os.path.join(os.path.dirname(__file__), c.data_downloads.downloads_page), "w"
    ) as fout:
        fout.writelines(out_txt)


###############################################################################
# Create staging repository content
###############################################################################


@task(
    help={
        "prerelease": "A pre release for user testing",
        "prerelease_url": "The URL of the pre release",
        "prerelease_time": "The time of the pre release",
        "prerelease_filename": "The filename of the plugin zip file",
    }
)
def generate_plugin_repo_xml(
    c,
    prerelease=False,
    prerelease_url=None,
    prerelease_time=None,
    prerelease_filename=None,
):
    """Generates the plugin repository xml file, from which users
    can use to install the plugin in QGIS.

    """
    repo_base_dir = Path(
        os.path.join(os.path.dirname(c.plugin.source_dir), "docs", "repository")
    )

    repo_base_dir.mkdir(parents=True, exist_ok=True)
    metadata = _get_metadata(c)
    fragment_template = """
            <pyqgis_plugin name="{name}" version="{version}">
                <description><![CDATA[{description}]]></description>
                <about><![CDATA[{about}]]></about>
                <version>{version}</version>
                <qgis_minimum_version>{qgis_minimum_version}</qgis_minimum_version>
                <homepage><![CDATA[{homepage}]]></homepage>
                <file_name>{filename}</file_name>
                <icon>{icon}</icon>
                <author_name><![CDATA[{author}]]></author_name>
                <download_url>{download_url}</download_url>
                <update_date>{update_date}</update_date>
                <experimental>{experimental}</experimental>
                <deprecated>{deprecated}</deprecated>
                <tracker><![CDATA[{tracker}]]></tracker>
                <repository><![CDATA[{repository}]]></repository>
                <tags><![CDATA[{tags}]]></tags>
                <server>False</server>
            </pyqgis_plugin>
    """.strip()
    contents = "<?xml version = '1.0' encoding = 'UTF-8'?>\n<plugins>"
    if prerelease:
        all_releases = [
            {
                "pre_release": prerelease,
                "tag_name": get_version(c),
                "url": prerelease_url,
                "published_at": datetime.strptime(
                    prerelease_time, "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
        ]
    else:
        all_releases = _get_existing_releases(c)

    if prerelease:
        target_releases = all_releases
    else:
        target_releases = _get_latest_releases(all_releases)

    for release in [r for r in target_releases if r is not None]:
        fragment = fragment_template.format(
            name=metadata.get("name"),
            version=metadata.get("version"),
            description=metadata.get("description"),
            about=metadata.get("about"),
            qgis_minimum_version=metadata.get("qgisMinimumVersion"),
            homepage=metadata.get("homepage"),
            filename=release.get("url").rpartition("/")[-1]
            if not prerelease_filename
            else prerelease_filename,
            icon=metadata.get("icon", ""),
            author="test",
            download_url=release.get("url"),
            update_date=release.get("published_at"),
            experimental=False,
            deprecated=metadata.get("deprecated"),
            tracker=metadata.get("tracker"),
            repository=metadata.get("repository"),
            tags=metadata.get("tags"),
        )
        contents = "\n".join((contents, fragment))
    contents = "\n".join((contents, "</plugins>"))
    repo_index = repo_base_dir / "plugins.xml"
    repo_index.write_text(contents, encoding="utf-8")

    return contents


def _get_metadata(c):
    """Reads the metadata properties from the
       project metadata file 'metadata.txt'.

    :return: plugin metadata
    :type: Dict
    """
    metadata = {}
    metadata_path = os.path.join(c.plugin.source_dir, "metadata.txt")

    with open(metadata_path, "r") as fh:
        for line in fh:
            # Skip empty lines
            line = line.strip()
            if not line:
                continue

            # Split key and value
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            metadata[key.strip()] = value.strip()

    # Update metadata with additional derived fields
    metadata.update(
        {
            "tags": metadata.get("tags", "").split(", ") if "tags" in metadata else [],
            "changelog": metadata.get("changelog", ""),
        }
    )

    return metadata


def _get_existing_releases(c):
    """Gets the existing plugin releases available in the GitHub repository.

    :returns: List of GitHub releases in dictionary format
    :rtype: List[dict]
    """
    # Set up the base URL for GitHub releases
    base_url = c.github.releases_url

    # Start a session with requests
    session = requests.Session()

    # Get the releases from GitHub
    response = session.get(base_url)

    releases = []
    if response.status_code == 200:
        payload = response.json()
        for release in payload:
            zip_download_url = None
            for asset in release.get("assets", []):
                if asset.get("content_type") == "application/zip":
                    zip_download_url = asset.get("browser_download_url")
                    break

            # If a zip URL was found, append the release info to the list
            if zip_download_url:
                releases.append(
                    {
                        "pre_release": release.get("prerelease", True),
                        "tag_name": release.get("tag_name"),
                        "url": zip_download_url,
                        "published_at": datetime.strptime(
                            release["published_at"], "%Y-%m-%dT%H:%M:%SZ"
                        ),
                    }
                )
    else:
        # Handle the case where GitHub API returns an error
        raise Exception(
            f"Failed to fetch releases: {response.status_code} {response.text}"
        )

    return releases


def _get_latest_releases(
    current_releases,
):
    """Searches for the latest plugin releases from the GitHub plugin releases.

    :param current_releases: Existing plugin releases available in the GitHub repository.
    :type current_releases: list of dicts

    :returns: Tuple containing the latest stable and experimental releases
    :rtype: tuple of dicts
    """
    latest_experimental = None
    latest_stable = None

    for release in current_releases or []:
        # Check if it's a pre-release (experimental)
        if release.get("pre_release"):
            if latest_experimental is not None:
                if release["published_at"] > latest_experimental["published_at"]:
                    latest_experimental = release
            else:
                latest_experimental = release
        # Check for stable release (non-pre-release)
        else:
            if latest_stable is not None:
                if release["published_at"] > latest_stable["published_at"]:
                    latest_stable = release
            else:
                latest_stable = release

    return latest_stable, latest_experimental


###############################################################################
# Package plugin zipfile
###############################################################################


@task(
    help={
        "clean": "Clean out dependencies before packaging",
        "version": "what version of QGIS to prepare ZIP file for",
        "tests": "Package tests with plugin",
        "filename": "Name for output file",
        #'python': 'Python to use for setup and compiling',
        "pip": 'Path to pip (usually "pip" or "pip3"',
        "tag": "Whether to tag on Github",
    }
)
def zipfile_build(
    c, clean=True, version=3, tests=False, filename=None, pip="pip", tag=False
):
    """Create plugin package"""
    set_version(c, modules=True)

    if tag:
        set_tag(c)
    else:
        print(
            "***Not setting tag on github***\nIf this is a "
            "production deployment you MUST tag this version on github, "
            "so cancel this process and re-run with tag=True"
        )

    plugin_setup(c, clean=clean, pip=pip)

    # Remove all .pyc files from source directory (QGIS plugin repo rejects them)
    print("Removing .pyc files from source directory...")
    pyc_count = 0
    for root, dirs, files in os.walk(c.plugin.source_dir):
        for file in files:
            if file.endswith(".pyc"):
                pyc_path = os.path.join(root, file)
                try:
                    os.remove(pyc_path)
                    pyc_count += 1
                except OSError as e:
                    print(f"Warning: Could not remove {pyc_path}: {e}")

    if pyc_count > 0:
        print(f"Removed {pyc_count} .pyc files")
    else:
        print("No .pyc files found to remove")

    # Make sure compiled versions of translation files are included
    lrelease(c)

    package_dir = c.plugin.package_dir

    if sys.version_info[0] < 3:
        if not os.path.exists(package_dir):
            os.makedirs(package_dir)
    else:
        os.makedirs(package_dir, exist_ok=True)

    if not filename:
        # Use plugin version in filename instead of QGIS version
        plugin_version = get_version(c)
        filename = os.path.join(
            package_dir, "{}_{}.zip".format(c.plugin.name, plugin_version)
        )

    print(f"Removing untracked datafiles from {c.plugin.data_dir}...")
    subprocess.check_call(["git", "clean", "-f", "-x", c.plugin.data_dir])

    print("Building zipfile...")
    with zipfile.ZipFile(filename, "w", zipfile.ZIP_DEFLATED) as zf:
        if not tests:
            c.plugin.excludes.extend(c.plugin.tests)
        _make_zip(zf, c)

    return filename


def _make_zip(zipFile, c):
    src_dir = c.plugin.source_dir

    for root, dirs, files in os.walk(c.plugin.source_dir):
        relpath = os.path.relpath(root)

        # Apply project excludes first
        files = _filter_excludes(root, files, c)
        dirs = _filter_excludes(root, dirs, c)

        # Do not descend into symlinked directories
        for d in list(dirs):
            d_path = os.path.join(root, d)
            if os.path.islink(d_path):
                print(f"Skipping symlinked directory: {d_path}")
                dirs.remove(d)

        # Write regular files only; skip symlinks and .pyc files
        for f in files:
            src_path = os.path.join(root, f)
            if os.path.islink(src_path):
                print(f"Skipping symlink: {src_path}")
                continue
            # Skip .pyc files - QGIS plugin repository rejects them for security
            if f.endswith(".pyc"):
                continue
            zipFile.write(src_path, os.path.join(relpath, f))

    # Include the license file within the plugin zipfile (it is in root of
    # repo, so otherwise would be skipped)
    zipFile.write("LICENSE", os.path.join(os.path.relpath(src_dir), "LICENSE"))


@task(
    help={
        "qgis": "QGIS version to target",
        "clean": "Clean out dependencies and untracked data files before packaging",
        "pip": 'Path to pip (usually "pip" or "pip3"',
        "tag": "Whether to tag on Github",
        "filename": "Name for output file",
    }
)
def zipfile_deploy(c, qgis, clean=True, pip="pip", tag=False, filename=None):
    filename = zipfile_build(c, pip=pip, clean=clean, tag=tag, filename=filename)
    client = _get_s3_client()

    print("Uploading package to S3")
    data = open(filename, "rb")
    client.put_object(
        Key="sharing/{}".format(os.path.basename(filename)),
        Body=data,
        Bucket=c.sphinx.zipfile_deploy_s3_bucket,
    )
    data.close()
    print("Package uploaded")


# Function
def _recursive_dir_create(d):
    if sys.version_info[0] < 3:
        if not os.path.exists(d):
            os.makedirs(os.path.join(os.path.abspath(os.path.dirname(d)), ""))
    else:
        os.makedirs(
            os.path.join(os.path.abspath(os.path.dirname(d)), ""), exist_ok=True
        )


def _get_s3_client():
    try:
        with open(
            os.path.join(os.path.dirname(__file__), "aws_credentials.json")
        ) as fin:
            keys = json.load(fin)
        client = boto3.client(
            "s3",
            aws_access_key_id=keys["access_key_id"],
            aws_secret_access_key=keys["secret_access_key"],
        )
    except OSError:
        print(
            "Warning: AWS credentials file not found. Credentials must be in environment variable or in default AWS credentials location."
        )
        client = boto3.client("s3")

    return client


def _s3_sync(c, bucket, s3_prefix, local_folder, patterns=["*"]):
    client = _get_s3_client()

    objects = client.list_objects(Bucket=bucket, Prefix="{}/".format(s3_prefix))[
        "Contents"
    ]

    for obj in objects:
        filename = os.path.basename(obj["Key"])

        if filename == "":
            # Catch the case of the key pointing to the root of the bucket and
            # skip it

            continue
        local_path = os.path.join(local_folder, filename)

        # First ensure all the files that are on S3 are up to date relative to
        # the local files, copying files in either direction as necessary

        if os.path.exists(local_path):
            if not _check_hash(obj["ETag"].strip('"'), local_path):
                lm_s3 = obj["LastModified"]
                lm_local = datetime.fromtimestamp(
                    os.path.getmtime(local_path), lm_s3.tzinfo
                )

                if lm_local > lm_s3:
                    print(
                        "Local version of {} is newer than on S3 - copying to S3.".format(
                            filename
                        )
                    )
                    data = open(local_path, "rb")
                    client.put_object(
                        Key="{}/{}".format(s3_prefix, os.path.basename(filename)),
                        Body=data,
                        Bucket=bucket,
                    )
                    data.close()
                else:
                    print(
                        "S3 version of {} is newer than local - copying to local.".format(
                            filename
                        )
                    )
                    _recursive_dir_create(local_path)
                    client.download_file(
                        Key="{}/{}".format(s3_prefix, os.path.basename(filename)),
                        Bucket=bucket,
                        Filename=local_path,
                    )
        else:
            print("Local version of {} is missing - copying to local.".format(filename))
            _recursive_dir_create(local_path)
            client.download_file(
                Key="{}/{}".format(s3_prefix, os.path.basename(filename)),
                Bucket=bucket,
                Filename=local_path,
            )

    # Now copy back to S3 any files that aren't yet there
    files = [glob.glob(pattern) for pattern in patterns]
    files = [item for sublist in files for item in sublist]
    s3_objects = client.list_objects(Bucket=bucket, Prefix="{}/".format(s3_prefix))[
        "Contents"
    ]
    s3_object_names = [os.path.basename(obj["Key"]) for obj in s3_objects]

    for f in files:
        if os.path.isdir(f):
            continue

        if os.path.basename(f) not in s3_object_names:
            print("S3 is missing {} - copying to S3.".format(f))
            data = open(f, "rb")
            client.put_object(
                Key="{}/{}".format(s3_prefix, os.path.basename(f)),
                Body=data,
                Bucket=bucket,
            )
            data.close()


def _check_hash(expected, filename):
    md5hash = hashlib.md5(open(filename, "rb").read()).hexdigest()

    if md5hash == expected:
        return True
    else:
        return False


def _get_api_token(c):
    base_url = getattr(c.trends_earth_api, "url", None)
    if base_url is None:
        raise RuntimeError("Trends.Earth API base URL is not configured.")

    email = getattr(c.trends_earth_api, "email", None) or os.environ.get(
        "TRENDS_EARTH_API_USER"
    )
    password = getattr(c.trends_earth_api, "password", None) or os.environ.get(
        "TRENDS_EARTH_API_PASSWORD"
    )

    if not email or not password:
        raise RuntimeError(
            "Trends.Earth API credentials are not configured. "
            "Set c.trends_earth_api.user/password or provide the "
            "TRENDS_EARTH_API_USER and TRENDS_EARTH_API_PASSWORD environment variables."
        )

    try:
        auth_response = requests.post(
            f"{base_url}/auth", json={"email": email, "password": password}
        )
        auth_response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        raise RuntimeError("Failed to authenticate with Trends.Earth API.") from exc

    try:
        auth_payload = auth_response.json()
    except ValueError as exc:
        raise RuntimeError("Authentication response was not valid JSON.") from exc

    token = auth_payload.get("access_token")
    if not token:
        raise RuntimeError("Authentication response did not include an access token.")
    return token


@task(
    help={
        "release_type": "geoBoundaries release type to download (default: gbOpen)",
        "output": "Optional output path for the saved JSON (defaults to LDMP/data)",
    }
)
def download_boundaries_cache(c, release_type="gbOpen", output=None):
    """Download and cache the boundaries list JSON used by the plugin."""

    print("Authenticating with Trends.Earth API...")

    token = _get_api_token(c)
    base_url = getattr(c.trends_earth_api, "url", None)
    if base_url is None:
        raise RuntimeError("Trends.Earth API base URL is not configured.")

    endpoint = f"{base_url}/api/v1/data/boundaries/list"

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }

    print(f"Requesting boundaries list from {endpoint} (release_type={release_type})")
    response = requests.get(
        endpoint, params={"release_type": release_type}, headers=headers
    )

    response.raise_for_status()
    payload = response.json()

    boundaries_list = payload.get("boundaries") or payload.get("data")
    if not boundaries_list:
        raise RuntimeError("Boundaries list response did not contain any data.")

    last_updated = payload.get("last_updated") or (
        (payload.get("meta") or {}).get("last_updated")
    )

    cache_payload = {
        "_cache_metadata": {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "server_last_updated": last_updated,
        },
        "data": boundaries_list,
    }

    if output:
        target_path = Path(output).resolve()
    else:
        target_path = (
            Path(c.plugin.source_dir) / "data" / f"boundaries_list_{release_type}.json"
        ).resolve()

    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        print(f"Overwriting existing file at {target_path}")

    with target_path.open("w", encoding="utf-8") as handle:
        json.dump(cache_payload, handle, indent=2)

    print(
        f"Saved boundaries list ({release_type}) to {target_path}."
        + (f" Last updated timestamp: {last_updated}." if last_updated else "")
    )


@task
def testdata_sync(c):
    _s3_sync(
        c,
        c.sphinx.zipfile_deploy_s3_bucket,
        "plugin_testdata",
        "LDMP/test/integration/fixtures",
        c.plugin.testdata_patterns,
    )


###############################################################################
# Options
###############################################################################

ns = Collection(
    set_version,
    set_tag,
    plugin_setup,
    plugin_install,
    compile_files,
    docs_build,
    docs_spellcheck,
    generate_plugin_repo_xml,
    translate_pull,
    translate_push,
    lrelease,
    changelog_build,
    tecli_login,
    tecli_clear,
    tecli_config,
    tecli_publish,
    tecli_run,
    tecli_info,
    tecli_logs,
    zipfile_build,
    zipfile_deploy,
    release_github,
    update_script_ids,
    testdata_sync,
    rtd_pre_build,
    build_download_page,
    download_boundaries_cache,
    list_scripts,
)

ns.configure(
    {
        "plugin": {
            "name": "LDMP",
            "ext_libs": {"path": "LDMP/ext-libs", "local_modules": []},
            "gui_dir": "LDMP/gui",
            "source_dir": "LDMP",
            "data_dir": "LDMP/data",
            "i18n_dir": "LDMP/i18n",
            "translations": ["fr", "es", "sw", "pt", "ar", "ru", "zh", "fa"],
            "testdata_patterns": ["LDMP/test/integration/fixtures/*"],
            "package_dir": "build",
            "tests": ["LDMP/test"],
            "excludes": [
                "LDMP/data_prep_scripts",
                "docs",
                "gee",
                "util",
                "*.pyc",
                "*.ts",
                "*.pro",
            ],
            # skip certain files inadvertently found by exclude pattern globbing
            "skip_exclude": [],
        },
        "trends_earth_api": {
            "url": "https://api.trends.earth",
            "email": None,
            "password": None,
        },
        "schemas": {
            "setup_dir": "LDMP/schemas",
        },
        "gee": {
            "script_dir": "gee",
            "scripts_json_file": "LDMP/data/scripts.json",
            "tecli": "../trends.earth-CLI/tecli",
        },
        "sphinx": {
            "sphinx_build": f"{sys.executable} -m sphinx.cmd.build",
            "sphinx_intl": "sphinx-intl",
            "docroot": "docs",
            "sourcedir": "docs/source",
            "builddir": "docs/build",
            "resourcedir": "docs/resources",
            "zipfile_deploy_s3_bucket": "trends.earth",
            "documentation_deploy_s3_bucket": "data.trends.earth",
            "docs_s3_prefix": "docs/",
            "transifex_name": "trendsearth-v2",
            "tx_path": f"{os.path.dirname(__file__)}/tx",
            "base_language": "en",
        },
        "data_downloads": {
            "downloads_page": "docs/source/for_users/downloads/index.md",
            "s3_bucket": "data.trends.earth",
            "s3_prefix": "unccd_reporting/2016-2023/packages/",
        },
        "github": {
            "api_url": "https://api.github.com",
            "repo_owner": "ConservationInternational",
            "repo_name": "trends.earth",
            "token": None,
            "releases_url": "https://api.github.com/repos/ConservationInternational/trends.earth/releases",
        },
    }
)
