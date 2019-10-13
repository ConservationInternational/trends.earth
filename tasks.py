# -*- coding: utf-8 -*-

import os
import sys
import platform
import fnmatch
import re
import glob
import stat
import shutil
import subprocess
from tempfile import mkstemp
import zipfile
import json
from datetime import datetime
import hashlib

import boto3
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
    valid = {"yes": True, "y": True, "ye": True,
             "no": False, "n": False}
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
        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("Please respond with 'yes' or 'no' "
                             "(or 'y' or 'n').\n")

def get_version():
    with open('version.txt', 'r') as f:
        v = f.read()
    return v.strip('\n')

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
                print('Permission error: unable to remove {}. Skipping that file.'.format(filename))
        for name in dirs:
            try:
                os.rmdir(os.path.join(root, name))
            except OSError:
                print('Unable to remove directory {}. Skipping removing that folder.'.format(os.path.join(root, name)))
    try:
        os.rmdir(top)
    except OSError:
        print('Unable to remove directory {}. Skipping removing that folder.'.format(top))


# Function to find and replace in a file
def _replace(file_path, regex, subst):
    #Create temp file
    fh, abs_path = mkstemp()
    if sys.version_info[0] < 3:
        with os.fdopen(fh,'w') as new_file:
            with open(file_path) as old_file:
                for line in old_file:
                    new_file.write(regex.sub(subst, line))
    else:
        with open(fh, 'w', encoding='Latin-1') as new_file:
            with open(file_path, encoding='Latin-1') as old_file:
                for line in old_file:
                    new_file.write(regex.sub(subst, line))
    os.remove(file_path)
    shutil.move(abs_path, file_path)


###############################################################################
# Misc development tasks (change version, deploy GEE scripts)
###############################################################################

@task(help={'version': 'Version to set'})
def set_version(c, v):
    # Validate the version matches the regex
    if not v or not re.match("[0-9]+([.][0-9]+)+", v):
        print('Must specify a valid version (example: 0.36)')
        return
    
    # Set in version.txt
    print('Setting version to {} in version.txt'.format(v))
    with open('version.txt', 'w') as f:
        f.write(v)
     
    # Set in Sphinx docs in make.conf
    print('Setting version to {} in sphinx conf.py'.format(v))
    sphinx_regex = re.compile("(((version)|(release)) = ')[0-9]+([.][0-9]+)+", re.IGNORECASE)
    _replace(os.path.join(c.sphinx.sourcedir, 'conf.py'), sphinx_regex, '\g<1>' + v)

    # Set in metadata.txt
    print('Setting version to {} in metadata.txt'.format(v))
    sphinx_regex = re.compile("^(version=)[0-9]+([.][0-9]+)+")
    _replace(os.path.join(c.plugin.source_dir, 'metadata.txt'), sphinx_regex, '\g<1>' + v)
    
    # Set in __init__.py
    print('Setting version to {} in __init__.py'.format(v))
    init_regex = re.compile('^(__version__[ ]*=[ ]*["\'])[0-9]+([.][0-9]+)+')
    _replace(os.path.join(c.plugin.source_dir, '__init__.py'), init_regex, '\g<1>' + v)

    # For the GEE config files the version can't have a dot, so convert to 
    # underscore
    v_gee = v.replace('.', '_')
    if not v or not re.match("[0-9]+(_[0-9]+)+", v_gee):
        print('Must specify a valid version (example: 0.36)')
        return

    gee_id_regex = re.compile('(, )?"id": "[0-9a-z-]*"(, )?')
    gee_script_name_regex = re.compile('("name": "[0-9a-zA-Z -]*)( [0-9]+(_[0-9]+)+)?"')

    # Set version for GEE scripts
    for subdir, dirs, files in os.walk(c.gee.script_dir):
        for file in files:
            filepath = os.path.join(subdir, file)
            if file == 'configuration.json':
                # Validate the version matches the regex
                print('Setting version to {} in {}'.format(v, filepath))
                # Update the version string
                _replace(filepath, gee_script_name_regex, '\g<1> ' + v_gee + '"')
                # Clear the ID since a new one will be assigned due to the new name
                _replace(filepath, gee_id_regex, '')
            elif file == '__init__.py':
                print('Setting version to {} in {}'.format(v, filepath))
                init_regex = re.compile('^(__version__[ ]*=[ ]*["\'])[0-9]+([.][0-9]+)+')
                _replace(filepath, init_regex, '\g<1>' + v)
    
    # Set in scripts.json
    print('Setting version to {} in scripts.json'.format(v))
    scripts_regex = re.compile('("script version": ")[0-9]+([-._][0-9]+)+', re.IGNORECASE)
    _replace(os.path.join(c.plugin.source_dir, 'data', 'scripts.json'), scripts_regex, '\g<1>' + v)

    # Set in setup.py
    print('Setting version to {} in trends.earth-schemas setup.py'.format(v))
    setup_regex = re.compile("^([ ]*version=[ ]*')[0-9]+([.][0-9]+)+")
    _replace(os.path.join(c.schemas.setup_dir, 'setup.py'), setup_regex, '\g<1>' + v)


def check_tecli_python_version():
    if sys.version_info[0] < 3:
        print("ERROR: tecli tasks require Python version > 2 (you are running Python version {}.{})".format(sys.version_info[0], sys.version_info[1]))
        return False
    else:
        return True

@task
def tecli_login(c):
    if not check_tecli_python_version():
        return
    subprocess.check_call(['python', os.path.abspath(c.gee.tecli), 'login'])

@task(help={'script': 'Script name'})
def tecli_publish(c, script=None):
    if not check_tecli_python_version():
        return
    if not script:
        ret = query_yes_no('WARNING: this will overwrite all scripts on the server with version {}.\nDo you wish to continue?'.format(get_version()))
        if not ret:
            return

    dirs = next(os.walk(c.gee.script_dir))[1]
    n = 0
    for dir in dirs:
        script_dir = os.path.join(c.gee.script_dir, dir) 
        if os.path.exists(os.path.join(script_dir, 'configuration.json')) and \
                (script == None or script == dir):
            print('Publishing {}...'.format(dir))
            subprocess.check_call(['python',
                                   os.path.abspath(c.gee.tecli),
                                   'publish', '--public=True', '--overwrite=True'], cwd=script_dir)
            n += 1
    if script and n == 0:
        print('Script "{}" not found.'.format(script))

@task(help={'script': 'Script name'})
def tecli_run(c, script):
    if not check_tecli_python_version():
        return
    dirs = next(os.walk(c.gee.script_dir))[1]
    n = 0
    script_dir = None
    for dir in dirs:
        script_dir = os.path.join(c.gee.script_dir, dir) 
        if os.path.exists(os.path.join(script_dir, 'configuration.json')) and \
                 script == dir:
            print('Running {}...'.format(dir))
            subprocess.check_call(['python', os.path.abspath(c.gee.tecli), 'start'], cwd=script_dir)
                                   
            n += 1
            break
    if script and n == 0:
        print('Script "{}" not found.'.format(script))

###############################################################################
# Setup dependencies and install package
###############################################################################

def read_requirements():
    """Return a list of runtime and list of test requirements"""
    with open('requirements.txt') as f:
        lines = f.readlines()
    lines = [ l for l in [ l.strip() for l in lines] if l ]
    divider = '# test requirements'

    try:
        idx = lines.index(divider)
    except ValueError:
        raise BuildFailure(
            'Expected to find "{}" in requirements.txt'.format(divider))

    not_comments = lambda s,e: [ l for l in lines[s:e] if l[0] != '#']
    return not_comments(0, idx), not_comments(idx+1, None)

@task(help={'clean': 'Clean out dependencies first'})
def plugin_setup(c, clean=False):
    '''install dependencies'''
    ext_libs = os.path.abspath(c.plugin.ext_libs)
    if clean and os.path.exists(ext_libs):
        shutil.rmtree(ext_libs)
    os.makedirs(ext_libs, exist_ok=True)
    runtime, test = read_requirements()

    os.environ['PYTHONPATH'] = ext_libs
    for req in runtime + test:
        # Don't install numpy with pyqtgraph as QGIS already has numpy. 
        # So use the --no-deps flag (-N for short) with that package only.
        if 'pyqtgraph' in req:
            subprocess.check_call(['pip', 'install', '--upgrade', '--no-deps', '-t', ext_libs, req])
        else:
            subprocess.check_call(['pip', 'install', '--upgrade', '-t', ext_libs, req])

@task(help={'clean': "run rmtree",
            'version': 'what version of QGIS to install to',
            'profile': 'what profile to install to (only applies to QGIS3',
            'python': 'Python to use for setup and compiling',
            'numba_recompile': 'Whether to recompile numba files even if they are existing'})
def plugin_install(c, clean=False, version=3, profile='default', python='python', numba_recompile=False):
    '''install plugin to qgis'''
    compile_files(c, version, clean, python, numba_recompile)
    plugin_name = c.plugin.name
    src = os.path.join(os.path.dirname(__file__), plugin_name)

    if version == 2:
        folder = '.qgis2'
    elif version == 3:
        if platform.system() == 'Darwin':
            folder = 'Library/Application Support/QGIS/QGIS3/profiles/'
        if platform.system() == 'Linux':
            folder = 'local/share/QGIS/QGIS3/profiles/'
        if platform.system() == 'Windows':
            folder ='AppData\\Roaming\\QGIS\\QGIS3\\profiles\\'
        folder = os.path.join(folder, profile)
    else:
        print("ERROR: unknown qgis version {}".format(version))
        return

    dst_plugins = os.path.join(os.path.expanduser('~'), folder, 'python', 'plugins')
    dst_this_plugin = os.path.join(dst_plugins, plugin_name)
    src = os.path.abspath(src)
    dst_this_plugin = os.path.abspath(dst_this_plugin)
    print("Installing to QGIS version {} plugin folder at {}".format(version, dst_this_plugin))

    if not hasattr(os, 'symlink') or (os.name == 'nt'):
        if clean:
            if os.path.exists(dst_this_plugin):
                rmtree(dst_this_plugin)
        for root, dirs, files in os.walk(src):
            relpath = os.path.relpath(root)
            if not os.path.exists(os.path.join(dst_plugins, relpath)):
                os.makedirs(os.path.join(dst_plugins, relpath))
            for f in _filter_excludes(root, files, c):
                try:
                    shutil.copy(os.path.join(root, f), os.path.join(dst_plugins, relpath, f))
                except PermissionError:
                    print('Permission error: unable to copy {} to {}. Skipping that file.'.format(f, os.path.join(dst_plugins, relpath, f)))
            _filter_excludes(root, dirs, c)
    elif not dst_this_plugin.exists():
        src.symlink(dst_this_plugin)

# Compile all ui and resource files
def compile_files(c, version, clean, python, numba_recompile):
    # check to see if we have pyuic
    if version == 2:
        pyuic = 'pyuic4'
    elif version ==3:
        pyuic = 'pyuic5'
    else:
        print("ERROR: unknown qgis version {}".format(version))
        return
    pyuic_path = check_path(pyuic)

    if not pyuic_path:
        print("ERROR: {} is not in your path---unable to compile ui files".format(pyuic))
        return
    else:
        ui_files = glob.glob('{}/*.ui'.format(c.plugin.gui_dir))
        ui_count = 0
        skip_count = 0
        for ui in ui_files:
            if os.path.exists(ui):
                (base, ext) = os.path.splitext(ui)
                output = "{0}.py".format(base)
                if clean or file_changed(ui, output):
                    # Fix the links to c header files that Qt Designer adds to 
                    # UI files when QGIS custom widgets are used
                    ui_regex = re.compile("(<header>)qgs[a-z]*.h(</header>)", re.IGNORECASE)
                    _replace(ui, ui_regex, '\g<1>qgis.gui\g<2>')
                    print("Compiling {0} to {1}".format(ui, output))
                    subprocess.check_call([pyuic_path, '-x', ui, '-o', output])
                    ui_count += 1
                else:
                    skip_count += 1
            else:
                print("{} does not exist---skipped".format(ui))
        print("Compiled {} UI files. Skipped {}.".format(ui_count, skip_count))

    # check to see if we have pyrcc
    if version == 2:
        pyrcc = 'pyrcc4'
    elif version ==3:
        pyrcc = 'pyrcc5'
    else:
        print("ERROR: unknown qgis version {}".format(version))
        return
    pyrcc_path = check_path(pyrcc)

    if not pyrcc:
        print("ERROR: {} is not in your path---unable to compile resource file(s)".format(pyrcc))
        return
    else:
        res_files = c.plugin.resource_files
        res_count = 0
        skip_count = 0
        for res in res_files:
            if os.path.exists(res):
                (base, ext) = os.path.splitext(res)
                output = "{0}.py".format(base)
                if clean or file_changed(res, output):
                    print("Compiling {0} to {1}".format(res, output))
                    subprocess.check_call([pyrcc_path, '-o', output, res])
                    res_count += 1
                else:
                    skip_count += 1
            else:
                print("{} does not exist---skipped".format(res))
        print("Compiled {} resource files. Skipped {}.".format(res_count, skip_count))

    binaries_compile(c, clean, python, numba_recompile)

def file_changed(infile, outfile):
    try:
        infile_s = os.stat(infile)
        outfile_s = os.stat(outfile)
        return infile_s.st_mtime > outfile_s.st_mtime
    except:
        return True

def _filter_excludes(root, items, c):
    excludes = set(c.plugin.excludes + c.plugin.numba_aot_files)
    skips = c.plugin.skip_exclude

    exclude = lambda p: any([fnmatch.fnmatch(p, e) for e in excludes])
    if not items:
        return []

    # to prevent descending into dirs, modify the list in place
    for item in list(items):  # copy list or iteration values change
        itempath = os.path.join(os.path.relpath(root), item)
        if exclude(itempath) and item not in skips:
            #debug('Excluding {}'.format(itempath))
            items.remove(item)
    return items

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

    # Also look in folders under this python versions lib path
    folders = os.environ["PATH"].split(os.pathsep)
    folders.extend([x[0] for x in os.walk(os.path.join(os.path.dirname(sys.executable), 'Lib'))])
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

@task(help={'force': 'Force the download of the translations files regardless of whether timestamps on the local computer are newer than those on the server'})
def translate_pull(c, force=False):
    lrelease = check_path('lrelease')
    if not lrelease:
        print("ERROR: lrelease is not in your path---unable to release translation files")
        return
    print("Pulling transifex translations...")
    if force:
        subprocess.check_call(['tx', 'pull', '-s', '-f', '--parallel'])
    else:
        subprocess.check_call(['tx', 'pull', '-s', '--parallel'])
    print("Releasing translations using lrelease...")
    for translation in c.plugin.translations:
        subprocess.check_call([lrelease, os.path.join(c.plugin.i18n_dir, 'LDMP_{}.ts'.format(translation))])

# @task
# def translate_update_resources(c):
#     print("Updating transifex...")
#     subprocess.check_call("sphinx-intl update-txconfig-resources --pot-dir {docroot}/i18n/pot --transifex-project-name {transifex_name}".format(docroot=c.sphinx.docroot, transifex_name=c.sphinx.transifex_name))
#

@task(help={'force': 'Push source files to transifex without checking modification times'})
def translate_push(c, force=False):
    print("Building changelog...")
    changelog_build(c)

    print("Gathering strings...")
    gettext(c)
    print("Generating the pot files for the LDMP toolbox help files...")
    for translation in c.plugin.translations:
        subprocess.check_call("sphinx-intl --config {sourcedir}/conf.py update -p {docroot}/i18n/pot -l {lang}".format(sourcedir=c.sphinx.sourcedir, docroot=c.sphinx.docroot, lang=translation))

    print("Gathering strings for translation using pylupdate4...")
    pylupdate4 = check_path('pylupdate4')
    if not pylupdate4:
        print("ERROR: pylupdate4 is not in your path---unable to gather strings for translation")
        return
    else:
        subprocess.check_call([pylupdate4, os.path.join(c.plugin.i18n_dir, 'i18n.pro')])

    if force:
        subprocess.check_call('tx push --parallel -f -s')
    else:
        subprocess.check_call('tx push --parallel -s')


@task(help={'language': 'language'})
def gettext(c, language=None):
    if not language:
        language = c.sphinx.base_language
    SPHINX_OPTS = '-D language={lang} -A language={lang} {sourcedir}'.format(lang=language,
            sourcedir=c.sphinx.sourcedir)
    I18N_SPHINX_OPTS = '{sphinx_opts} {docroot}/i18n/pot'.format(docroot=c.sphinx.docroot, sphinx_opts=SPHINX_OPTS)
    subprocess.check_call("sphinx-build -b gettext -a {i18n_sphinx_opts}".format(i18n_sphinx_opts=I18N_SPHINX_OPTS))

###############################################################################
# Build documentation
###############################################################################

@task(help={'clean': 'clean out built artifacts first',
    'ignore_errors': 'ignore documentation errors',
    'language': "which language to build (all are built by default)",
    'fast': "only build english html docs"})
def docs_build(c, clean=False, ignore_errors=False, language=None, fast=False):
    if clean:
        c.sphinx.builddir.rmtree()

    if language:
        languages = [language]
    else:
        languages = [c.sphinx.base_language]
        languages.extend(c.plugin.translations)

    print("\nBuilding changelog...")
    changelog_build(c)

    for language in languages:
        print("\nBuilding {lang} documentation...".format(lang=language))
        SPHINX_OPTS = '-D language={lang} -A language={lang} {sourcedir}'.format(lang=language,
                sourcedir=c.sphinx.sourcedir)

        _localize_resources(c, language)

        subprocess.check_call("sphinx-intl --config {sourcedir}/conf.py build --language={lang}".format(sourcedir=c.sphinx.sourcedir,
            lang=language))

        # Build HTML docs
        if language != 'en' or ignore_errors:
            subprocess.check_call("sphinx-build -b html -a {sphinx_opts} {builddir}/html/{lang}".format(sphinx_opts=SPHINX_OPTS,
                builddir=c.sphinx.builddir, lang=language))
        else:
            subprocess.check_call("sphinx-build -n -W -b html -a {sphinx_opts} {builddir}/html/{lang}".format(sphinx_opts=SPHINX_OPTS,
                builddir=c.sphinx.builddir, lang=language))
        print("HTML Build finished. The HTML pages for '{lang}' are in {builddir}.".format(lang=language, builddir=c.sphinx.builddir))

        if fast:
            break

        # Build PDF, by first making latex from sphinx, then pdf from that
        tex_dir = "{builddir}/latex/{lang}".format(builddir=c.sphinx.builddir, lang=language)
        subprocess.check_call("sphinx-build -b latex -a {sphinx_opts} {tex_dir}".format(sphinx_opts=SPHINX_OPTS, tex_dir=tex_dir))

        for doc in c.sphinx.latex_documents:
            for n in range(3):
                # Run multiple times to ensure crossreferences are right
                subprocess.check_call(['xelatex', doc], cwd=tex_dir)
            # Move the PDF to the html folder so it will be uploaded with the 
            # site
            doc_pdf = os.path.splitext(doc)[0] + '.pdf'
            out_dir = '{builddir}/html/{lang}/pdfs'.format(builddir=c.sphinx.builddir, lang=language)
            if not os.path.exists(out_dir):
                os.makedirs(out_dir)
            shutil.move('{tex_dir}/{doc}'.format(tex_dir=tex_dir, doc=doc_pdf),
                        '{out_dir}/{doc}'.format(out_dir=out_dir, doc=doc_pdf))

def _localize_resources(c, language):
    print("Removing all static content from {sourcedir}/static.".format(sourcedir=c.sphinx.sourcedir))
    if os.path.exists('{sourcedir}/static'.format(sourcedir=c.sphinx.sourcedir)):
        rmtree('{sourcedir}/static'.format(sourcedir=c.sphinx.sourcedir))
    print("Copy 'en' (base) static content to {sourcedir}/static.".format(sourcedir=c.sphinx.sourcedir))
    if os.path.exists("{resourcedir}/en".format(resourcedir=c.sphinx.resourcedir)):
        shutil.copytree('{resourcedir}/en'.format(resourcedir=c.sphinx.resourcedir),
                        '{sourcedir}/static'.format(sourcedir=c.sphinx.sourcedir))
    print("Copy localized '{lang}' static content to {sourcedir}/static.".format(lang=language, sourcedir=c.sphinx.sourcedir))
    if language != 'en' and os.path.exists("{resourcedir}/{lang}".format(resourcedir=c.sphinx.resourcedir, lang=language)):
        src = '{resourcedir}/{lang}'.format(resourcedir=c.sphinx.resourcedir, lang=language)
        dst = '{sourcedir}/static'.format(sourcedir=c.sphinx.sourcedir)
        for item in os.listdir(src):
            s = os.path.join(src, item)
            d = os.path.join(dst, item)
            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)


@task
def changelog_build(c):
    out_txt = ['Changelog\n',
               '======================\n',
               '\n',
               'This page lists the version history of |trends.earth|.\n']

    with open(os.path.join(c.plugin.source_dir, 'metadata.txt'), 'r') as fin:
        metadata = fin.readlines()

    changelog_header_re = re.compile('^changelog=', re.IGNORECASE)
    version_header_re = re.compile('^[ ]*[0-9]+(\.[0-9]+){1,2}', re.IGNORECASE)

    at_changelog = False
    for line in metadata:
        if not at_changelog and not changelog_header_re.match(line):
            continue
        elif changelog_header_re.match(line):
            line = changelog_header_re.sub('  ', line)
            at_changelog = True
        version_header = version_header_re.match(line)
        if version_header:
            version_number = version_header.group(0)
            version_number = version_number.strip(' \n')
            line = line.strip(' \n')
            line = "\n`{} <https://github.com/ConservationInternational/trends.earth/releases/tag/{}>`_\n".format(line, version_number)
            line = [line, '-----------------------------------------------------------------------------------------------------------------------------\n\n']
        out_txt.extend(line)

    out_file = '{docroot}/source/about/changelog.rst'.format(docroot=c.sphinx.docroot)
    with open(out_file, 'w') as fout:
        metadata = fout.writelines(out_txt)

###############################################################################
# Package plugin zipfile
###############################################################################

@task(help={'clean': 'Clean out dependencies before packaging',
            'version': 'what version of QGIS to prepare ZIP file for',
            'tests': 'Package tests with plugin',
            'filename': 'Name for output file',
            'python': 'Python to use for setup and compiling',
            'numba_recompile': 'Whether to recompile numba files even if they are existing'})
def zipfile_build(c, clean=False, version=3, tests=False, filename=None, python='python', numba_recompile=False):
    """Create plugin package"""
    plugin_setup(c, clean)
    compile_files(c, version, clean, python, numba_recompile)
    binaries_sync(c)
    package_dir = c.plugin.package_dir
    if sys.version_info[0] < 3:
        if not os.path.exists(package_dir):
            os.makedirs(package_dir)
    else:
        os.makedirs(package_dir, exist_ok=True)
    #package_file =  os.path.join(package_dir, '{}_{}.zip'.format(c.plugin.name, get_version()))
    if not filename:
        filename =  os.path.join(package_dir, '{}_QGIS{}.zip'.format(c.plugin.name, version))
    print('Building zipfile...')
    with zipfile.ZipFile(filename, 'w', zipfile.ZIP_DEFLATED) as zf:
        if not tests:
            c.plugin.excludes.extend(c.plugin.tests)
        _make_zip(zf, c)
    return(filename)

def _make_zip(zipFile, c):
    src_dir = c.plugin.source_dir
    for root, dirs, files in os.walk(src_dir):
        for f in _filter_excludes(root, files, c):
            relpath = os.path.relpath(root)
            zipFile.write(os.path.join(root, f), os.path.join(relpath, f))
        _filter_excludes(root, dirs, c)

@task(help={'clean': 'Clean out dependencies before packaging',
            'python': 'Python to use for setup and compiling'})
def zipfile_deploy(c, clean=False, python='python'):
    filename = zipfile_build(c, python=python)
    try:
        with open(os.path.join(os.path.dirname(__file__), 'aws_credentials.json'), 'r') as fin:
            keys = json.load(fin)
        client = boto3.client('s3',
                              aws_access_key_id=keys['access_key_id'],
                              aws_secret_access_key=keys['secret_access_key'])
    except IOError:
        print('Warning: AWS credentials file not found. Credentials must be in environment variable.')
        client = boto3.client('s3')
    print('Uploading package to S3')
    data = open(filename, 'rb')
    client.put_object(Key='sharing/{}'.format(os.path.basename(filename)),
                      Body=data, 
                      Bucket=c.sphinx.deploy_s3_bucket)
    data.close()
    print('Package uploaded')


# Function 
def _recursive_dir_create(d):
    os.makedirs(os.path.join(os.path.abspath(os.path.dirname(d)), ''), exist_ok=True)


def _s3_sync(c, bucket, s3_prefix, local_folder, patterns=['*']):
    try:
        with open(os.path.join(os.path.dirname(__file__), 'aws_credentials.json'), 'r') as fin:
            keys = json.load(fin)
        client = boto3.client('s3',
                              aws_access_key_id=keys['access_key_id'],
                              aws_secret_access_key=keys['secret_access_key'])
    except IOError:
        print('Warning: AWS credentials file not found. Credentials must be in environment variable.')
        client = boto3.client('s3')
    
    objects = client.list_objects(Bucket=bucket, Prefix='{}/'.format(s3_prefix))['Contents']
    for obj in objects:
        filename = os.path.basename(obj['Key'])
        if filename == '':
            # Catch the case of the key pointing to the root of the bucket and 
            # skip it
            continue
        local_path = os.path.join(local_folder, filename)

        # First ensure all the files that are on S3 are up to date relative to 
        # the local files, copying files in either direction as necessary
        if os.path.exists(local_path):
            if not _check_hash(obj['ETag'].strip('"'), local_path):
                lm_s3 = obj['LastModified']
                lm_local = datetime.fromtimestamp(os.path.getmtime(local_path), lm_s3.tzinfo)
                if lm_local > lm_s3:
                    print('Local version of {} is newer than on S3 - copying to S3.'.format(filename))
                    data = open(local_path, 'rb')
                    client.put_object(Key='{}/{}'.format(s3_prefix, os.path.basename(filename)),
                                      Body=data, 
                                      Bucket=bucket)
                    data.close()
                else:
                    print('S3 version of {} is newer than local - copying to local.'.format(filename))
                    _recursive_dir_create(local_path)
                    client.download_file(Key='{}/{}'.format(s3_prefix, os.path.basename(filename)),
                                         Bucket=bucket,
                                         Filename=local_path)
        else:
            print('Local version of {} is missing - copying to local.'.format(filename))
            _recursive_dir_create(local_path)
            client.download_file(Key='{}/{}'.format(s3_prefix, os.path.basename(filename)),
                                 Bucket=bucket,
                                 Filename=local_path)

    # Now copy back to S3 any files that aren't yet there
    files = [glob.glob(pattern) for pattern in patterns]
    files = [item for sublist in files for item in sublist]
    s3_objects = client.list_objects(Bucket=bucket, Prefix='{}/'.format(s3_prefix))['Contents']
    s3_object_names = [os.path.basename(obj['Key']) for obj in s3_objects]
    for f in files:
        if not os.path.basename(f) in s3_object_names:
            print('S3 is missing {} - copying to S3.'.format(f))
            data = open(f, 'rb')
            client.put_object(Key='{}/{}'.format(s3_prefix, os.path.basename(f)),
                              Body=data, 
                              Bucket=bucket)
            data.close()


def _check_hash(expected, filename):
    md5hash = hashlib.md5(open(filename, 'rb').read()).hexdigest()
    if md5hash == expected:
        return True
    else:
        return False


@task
def binaries_sync(c):
    try:
        with open(os.path.join(os.path.dirname(__file__), 'aws_credentials.json'), 'r') as fin:
            keys = json.load(fin)
        client = boto3.client('s3',
                              aws_access_key_id=keys['access_key_id'],
                              aws_secret_access_key=keys['secret_access_key'])
    except IOError:
        print('Warning: AWS credentials file not found. Credentials must be in environment variable.')
        client = boto3.client('s3')

    _s3_sync(c, c.sphinx.deploy_s3_bucket, 'plugin_binaries', 'LDMP', c.plugin.numba_binary_patterns)


@task
def testdata_sync(c):
    try:
        with open(os.path.join(os.path.dirname(__file__), 'aws_credentials.json'), 'r') as fin:
            keys = json.load(fin)
        client = boto3.client('s3',
                              aws_access_key_id=keys['access_key_id'],
                              aws_secret_access_key=keys['secret_access_key'])
    except IOError:
        print('Warning: AWS credentials file not found. Credentials must be in environment variable.')
        client = boto3.client('s3')

    _s3_sync(c, c.sphinx.deploy_s3_bucket, 'plugin_testdata', 'LDMP/test/fixtures', c.plugin.testdata_patterns)


@task(help={'clean': 'Clean out dependencies before packaging',
            'python': 'Python to use for setup and compiling',
            'numba_recompile': 'Whether to recompile numba files even if they are existing'})
def binaries_compile(c, clean=False, python='python', numba_recompile=False):
    print("Compiling exported numba functions...")
    numba_files = c.plugin.numba_aot_files
    n = 0
    for numba_file in numba_files:
        (base, ext) = os.path.splitext(numba_file)
        output = "{0}.cp37-win_amd64.pyd".format(base)
        if numba_recompile or clean or file_changed(numba_file, output):
            subprocess.check_call([python, numba_file])
            n += 1
    print("Compiled {} numba files. Skipped {}.".format(n, len(numba_files) - n))


###############################################################################
# Options
###############################################################################

ns = Collection(set_version, plugin_setup, plugin_install,
                docs_build, translate_pull, translate_push,
                tecli_login, tecli_publish, tecli_run,
                zipfile_build, zipfile_deploy,
                binaries_compile, binaries_sync,
                testdata_sync)

ns.configure({
    'plugin': {
        'name': 'LDMP',
        'ext_libs': 'LDMP/ext-libs',
        'gui_dir': 'LDMP/gui',
        'source_dir': 'LDMP',
        'i18n_dir': 'LDMP/i18n',
        #'translations': ['fr', 'es', 'pt', 'sw', 'ar', 'ru', 'zh'],
        'translations': ['fr', 'es', 'sw', 'pt'],
        'resource_files': ['LDMP/resources.qrc'],
        'numba_aot_files': ['LDMP/calculate_numba.py',
                            'LDMP/summary_numba.py'],
        'numba_binary_patterns': ['LDMP/*.so',
                                  'LDMP/*.pyd'],
        'testdata_patterns': ['LDMP/test/fixtures/*'],
        'package_dir': 'build',
        'tests': ['LDMP/test'],
        'excludes': [
            'LDMP/data_prep_scripts',
            'docs',
            'gee',
            'util',
            '*.pyc'
            ],
        # skip certain files inadvertently found by exclude pattern globbing
        'skip_exclude': []
    },
    'schemas': {
        'setup_dir': 'LDMP/schemas',
    },
    'gee': {
        'script_dir': 'gee',
        'tecli': '../trends.earth-CLI/tecli'
    },
    'sphinx' : {
        'docroot': 'docs',
        'sourcedir': 'docs/source',
        'builddir': 'docs/build',
        'resourcedir': 'docs/resources',
        'deploy_s3_bucket': 'trends.earth',
        'docs_s3_prefix': 'docs/',
        'transifex_name': 'trendsearth',
        'base_language': 'en',
        'latex_documents': ['Trends.Earth.tex',
                           'Trends.Earth_Tutorial01_Installation.tex',
                           'Trends.Earth_Tutorial02_Computing_Indicators.tex',
                           'Trends.Earth_Tutorial03_Downloading_Results.tex',
						   'Trends.Earth_Tutorial04_Using_Custom_Productivity.tex',
						   'Trends.Earth_Tutorial05_Using_Custom_Land_Cover.tex',
						   'Trends.Earth_Tutorial06_Using_Custom_Soil_Carbon.tex',
                           'Trends.Earth_Tutorial07_Computing_SDG_Indicator.tex',
                           'Trends.Earth_Tutorial08_The_Summary_Table.tex',
                           'Trends.Earth_Tutorial09_Loading_a_Basemap.tex',
                           'Trends.Earth_Tutorial10_Forest_Carbon.tex',
						   'Trends.Earth_Tutorial11_Urban_Change_SDG_Indicator.tex']
    }
})
