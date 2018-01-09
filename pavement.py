# -*- coding: utf-8 -*-
import os
import sys
import re
import fnmatch
import json
import shutil
import subprocess
from tempfile import mkstemp

from paver.easy import *
from paver.doctools import html

options(
    gefcli=path('C:/Users/azvol/Code/LandDegradation/gef-cli/gefcli'),
    gefcli_venv_script=path('C:/Users/azvol/Code/LandDegradation/gef-cli/venv/Scripts/activate'),
)


# Function to find and replace in a file
def _replace(file_path, regex, subst):
    #Create temp file
    fh, abs_path = mkstemp()
    with os.fdopen(fh, 'w') as new_file:
        with open(file_path) as old_file:
            for line in old_file:
                new_file.write(regex.sub(subst, line))
    os.remove(file_path)
    shutil.move(abs_path, file_path)


@task
@cmdopts([
    ('version=', 'v', 'Version to set'),
])
def set_version(options):
    v = getattr(options, 'version', None)
    if not v:
        print('Must specify a valid version (example: 0.36)')
        return
    # For the config files the version can't have a dot, so convert to 
    # underscore
    v_config = v.replace('.', '_')
    if not v or not re.match("[0-9]+_[0-9]+", v_config):
        print('Must specify a valid version (example: 0.36)')
        return

    id_regex = re.compile('(, )?"id": "[0-9a-z-]*"(, )?')
    name_regex = re.compile('("name": "[0-9a-zA-Z -]*)( [0-9]+_[0-9]+)?"')

    for subdir, dirs, files in os.walk('.'):
        for file in files:
            filepath = os.path.join(subdir, file)
            if file == 'configuration.json':
                # Validate the version matches the regex
                print('Setting version to {} in {}'.format(v, filepath))
                # Update the version string
                _replace(filepath, name_regex, '\g<1> ' + v_config + '"')
                # Clear the ID since a new one will be assigned due to the new name
                _replace(filepath, id_regex, '')
            elif file == '__init__.py':
                print('Setting version to {} in {}'.format(v, filepath))
                init_regex = re.compile('^(__version__[ ]*=[ ]*["\'])[0-9]+[.][0-9]+')
                _replace(filepath, init_regex, '\g<1>' + v)

@task
def publish_all(options):
    dirs = next(os.walk('.'))[1]
    # print('Activating venv...')
    # subprocess.check_call(['source', options.gefcli_venv_script])
    subprocess.check_call(['python', options.gefcli, 'login'])
    for dir in dirs:
        if os.path.exists(os.path.join(dir, 'configuration.json')):
            print('Publishing {}...'.format(dir))
            subprocess.check_call(['python', options.gefcli, 'publish'], cwd=dir)

    #TODO: Make the scripts public after publishing


@task
@consume_args
def pep8(args):
    """Check code for PEP8 violations"""
    try:
        import pep8
    except:
        error('pep8 not found! Run "pip install autopep8".')
        sys.exit(1)

    # Errors to ignore
    ignore = ['E203', 'E121', 'E122', 'E123', 'E124', 'E125', 'E126', 'E127',
              'E128', 'E402']
    styleguide = pep8.StyleGuide(ignore=ignore,
                                 exclude=['*/ext-libs/*', '*/ext-src/*'],
                                 repeat=True, max_line_length=79,
                                 parse_argv=args)
    styleguide.input_dir(options.plugin.source_dir)
    info('===== PEP8 SUMMARY =====')
    styleguide.options.report.print_statistics()


@task
@consume_args
def autopep8(args):
    """Format code according to PEP8
    """
    try:
        import autopep8
    except:
        error('autopep8 not found! Run "paver install_devtools".')
        sys.exit(1)

    if any(x not in args for x in ['-i', '--in-place']):
        args.append('-i')

    args.append('--ignore=E261,E265,E402,E501')
    args.insert(0, 'dummy')

    cmd_args = autopep8.parse_args(args)

    excludes = ('ext-lib', 'ext-src')
    for p in path('.').walk():
        if any(exclude in p for exclude in excludes):
            continue

        if p.fnmatch('*.py'):
            autopep8.fix_file(p, options=cmd_args)


@task
@consume_args
def pylint(args):
    """Check code for errors and coding standard violations"""
    try:
        from pylint import lint
    except:
        error('pylint not found! Run "paver install_devtools".')
        sys.exit(1)

    if not 'rcfile' in args:
        args.append('--rcfile=pylintrc')

    args.append(options.plugin.source_dir)
    lint.Run(args)


################################################
# Below is based on pb_tool:
# https://github.com/g-sherman/plugin_build_tool
def check_path(app):
    """ Adapted from StackExchange:
        http://stackoverflow.com/questions/377017
    """

    def is_exe(fpath):
        return os.path.exists(fpath) and os.access(fpath, os.X_OK)

    def ext_candidates(fpath):
        yield fpath
        for ext in os.environ.get("PATHEXT", "").split(os.pathsep):
            yield fpath + ext

    fpath, fname = os.path.split(app)
    if fpath:
        if is_exe(app):
            return app
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            exe_file = os.path.join(path, app)
            for candidate in ext_candidates(exe_file):
                if is_exe(candidate):
                    return candidate

    return None
