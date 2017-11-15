# -*- coding: utf-8 -*-
import os
import sys
import fnmatch
import glob
import json
import stat
import shutil
import subprocess
import tinys3
import zipfile

from paver.easy import *
from paver.doctools import html

options(
    plugin = Bunch(
        name = 'LDMP',
        ext_libs = path('LDMP/ext-libs'),
        ext_src = path('LDMP/ext-src'),
        gui_dir = path('LDMP/gui'),
        source_dir = path('LDMP'),
        i18n_dir = path('LDMP/i18n'),
        translations = ['LDMP_fr.ts'],
        resource_files = [path('LDMP/resources.qrc')],
        package_dir = path('.'),
        tests = ['test'],
        excludes = [
            'LDMP/test',
            'LDMP/data_prep_scripts',
            'LDMP/help/make.bat',
            'LDMP/help/source',
            'LDMP/help/resources',
            'LDMP/help/build/gettext',
            'LDMP/help/i18n',
            '*.pyc',
        ],
        # skip certain files inadvertently found by exclude pattern globbing
        skip_exclude = []
    ),

    sphinx = Bunch(
        docroot = path('LDMP/help'),
        sourcedir = path('LDMP/help/source'),
        builddir = path('LDMP/help/build'),
        resourcedir = path('LDMP/help/resources'),
        docs_s3_bucket = 'landdegradation-docs',
        transifex_name = 'land_degradation_monitoring_toolbox_docs_1_0',
        language = 'en'
    )
)

# Handle long filenames or readonly files on windows, see: 
# http://bit.ly/2g58Yxu
def rmtree(top):
    for root, dirs, files in os.walk(top, topdown=False):
        for name in files:
            filename = os.path.join(root, name)
            os.chmod(filename, stat.S_IWUSR)
            os.remove(filename)
        for name in dirs:
            os.rmdir(os.path.join(root, name))
    os.rmdir(top)

@task
@cmdopts([
    ('clean', 'c', 'Clean out dependencies first'),
    ('develop', 'd', 'Do not alter source dependency git checkouts'),
])
def setup(options):
    """Install run-time dependencies"""
    clean = options.get('clean', False)
    develop = options.get('develop', False)
    ext_libs = options.plugin.ext_libs
    ext_src = options.plugin.ext_src
    if clean:
        rmtree(ext_libs)
    ext_libs.makedirs()
    runtime, test = read_requirements()
    os.environ['PYTHONPATH'] = ext_libs.abspath()
    for req in runtime + test:
        if '#egg' in req:
            urlspec, req = req.split('#egg=')
            localpath = ext_src / req
            if not develop:
                if localpath.exists():
                    cwd = os.getcwd()
                    os.chdir(localpath)
                    print(localpath)
                    sh('git pull')
                    os.chdir(cwd)
                else:
                    sh('git clone  {} {}'.format(urlspec, localpath))
            req = localpath

        # Don't install numpy with pyqtgraph - QGIS already has numpy. So use 
        # the --no-deps flag (-N for short) with that package only.
        if 'pyqtgraph' in req:
            deps = '-N'
        else:
            deps = '-a'

        sh('easy_install {deps} -d {ext_libs} {dep}'.format(deps=deps,
           ext_libs=ext_libs.abspath(), dep=req))


@task
def translate(options):
    pylupdate4 = check_path('pylupdate4')
    if not pylupdate4:
        print("pylupdate4 is not in your path---unable to gather strings for translation")
    print("Gathering strings for translation using pylupdate4")
    subprocess.check_call([pylupdate4, os.path.join(options.plugin.i18n_dir, 'i18n.pro')])

    lrelease = check_path('lrelease')
    if not lrelease:
        print("lrelease is not in your path---unable to release translation files")
    print("Releasing translations using lrelease")
    for translation in options.plugin.translations:
        subprocess.check_call([lrelease, os.path.join(options.plugin.i18n_dir, translation)])

def read_requirements():
    """Return a list of runtime and list of test requirements"""
    lines = path('requirements.txt').lines()
    lines = [ l for l in [ l.strip() for l in lines] if l ]
    divider = '# test requirements'

    try:
        idx = lines.index(divider)
    except ValueError:
        raise BuildFailure(
            'Expected to find "{}" in requirements.txt'.format(divider))

    not_comments = lambda s,e: [ l for l in lines[s:e] if l[0] != '#']
    return not_comments(0, idx), not_comments(idx+1, None)


def _install(folder, options):
    '''install plugin to qgis'''
    if not options.get('fast', False):
        builddocs(options)
    compile_files(options)
    plugin_name = options.plugin.name
    src = path(__file__).dirname() / plugin_name
    dst_plugins = path('~').expanduser() / folder / 'python' / 'plugins'
    dst_this_plugin = dst_plugins / plugin_name
    src = src.abspath()
    dst_this_plugin = dst_this_plugin.abspath()
    if not hasattr(os, 'symlink') or (os.name == 'nt'):
        if dst_this_plugin.exists():
            rmtree(dst_this_plugin)
        for root, dirs, files in os.walk(src):
            relpath = os.path.relpath(root)
            if not path(path(dst_plugins) / path(relpath)).exists():
                os.makedirs(path(path(dst_plugins) / path(relpath)))
            for f in _filter_excludes(root, files, options):
                shutil.copy(path(root) / f, path(dst_plugins) / path(relpath) / f)
            _filter_excludes(root, dirs, options)
    elif not dst_this_plugin.exists():
        src.symlink(dst_this_plugin)

@task
@cmdopts([
    ('ignore_errors', 'i', 'ignore documentation errors'),
    ('fast', 'f', "don't build docs"),
])
def install(options):
    _install(".qgis2", options)

@task
@cmdopts([
    ('ignore_errors', 'i', 'ignore documentation errors'),
    ('fast', 'f', "don't build docs"),
])
def installdev(options):
    _install(".qgis-dev", options)

@task
@cmdopts([
    ('ignore_errors', 'i', 'ignore documentation errors'),
    ('fast', 'f', "don't build docs"),
])
def install3(options):
    _install(".qgis3", options)

@task
@cmdopts([
    ('ignore_errors', 'i', 'ignore documentation errors'),
    ('tests', 't', 'Package tests with plugin'),
])
def package(options):
    """Create plugin package"""
    builddocs(options)
    tests = options.get('tests', False)
    package_file = options.plugin.package_dir / '{}.zip'.format(options.plugin.name)
    with zipfile.ZipFile(package_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        if not tests:
            options.plugin.excludes.extend(options.plugin.tests)
        _make_zip(zf, options)
    return package_file


@task
@cmdopts([
    ('tests', 't', 'Package tests with plugin'),
    ('clean', 'c', 'Clean out dependencies first'),
    ('ignore_errors', 'i', 'ignore documentation errors'),
    ('develop', 'd', 'Do not alter source dependency git checkouts'),
])
def deploy(options):
    setup(options)
    package(options)
    with open(os.path.join(os.path.dirname(__file__), 'aws_credentials.json'), 'r') as fin:
        keys = json.load(fin)
    conn = tinys3.Connection(keys['access_key_id'], keys['secret_access_key'])
    f = open('LDMP.zip','rb')
    print('Uploading package to S3')
    conn.upload('Sharing/LDMP.zip', f, 'landdegradation', public=True)
    print('Package uploaded')

@task
@cmdopts([
    ('ignore_errors', 'i', 'ignore documentation errors'),
])
def deploy_docs(options):
    builddocs(options)

    with open(os.path.join(os.path.dirname(__file__), 'aws_credentials.json'), 'r') as fin:
        keys = json.load(fin)
    conn = tinys3.Connection(keys['access_key_id'], keys['secret_access_key'])

    print('Clearing existing docs.')
    pool = tinys3.Pool(keys['access_key_id'], keys['secret_access_key'], size=10)
    deletions = []
    for item in conn.list('', options.sphinx.docs_s3_bucket):
        deletions.append(pool.delete(item['key'], options.sphinx.docs_s3_bucket))
    pool.all_completed(deletions)
    print('Existing docs deleted.')

    print('Uploading docs to S3.')
    requests = []
    local_directory = options.sphinx.builddir / "html"
    for root, dirs, files in os.walk(local_directory):
        for filename in files:
            local_path = os.path.join(root, filename)
            relative_path = os.path.relpath(local_path, local_directory)
            print local_path, relative_path, options.sphinx.docs_s3_bucket
            f = open(local_path,'rb')
            requests.append(pool.upload(relative_path.replace('\\', '/'), f, 
                options.sphinx.docs_s3_bucket, public=True))
    pool.all_completed(requests)
    print('Docs uploaded.')

@task
def install_devtools():
    """Install development tools"""
    try:
        import pip
    except:
        error('FATAL: Unable to import pip, please install it first!')
        sys.exit(1)

    pip.main(['install', '-r', 'requirements-dev.txt'])


@task
@consume_args
def pep8(args):
    """Check code for PEP8 violations"""
    try:
        import pep8
    except:
        error('pep8 not found! Run "paver install_devtools".')
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
    for p in options.plugin.source_dir.walk():
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


def _filter_excludes(root, items, options):
    excludes = set(options.plugin.excludes)
    skips = options.plugin.skip_exclude

    exclude = lambda p: any([fnmatch.fnmatch(p, e) for e in excludes])
    if not items:
        return []

    # to prevent descending into dirs, modify the list in place
    for item in list(items):  # copy list or iteration values change
        itempath = path(os.path.relpath(root)) / item
        if exclude(itempath) and item not in skips:
            debug('Excluding {}'.format(itempath))
            items.remove(item)
    return items

def _make_zip(zipFile, options):
    src_dir = options.plugin.source_dir
    for root, dirs, files in os.walk(src_dir):
        for f in _filter_excludes(root, files, options):
            relpath = os.path.relpath(root)
            zipFile.write(path(root) / f, path(relpath) / f)
        _filter_excludes(root, dirs, options)

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

def file_changed(infile, outfile):
    try:
        infile_s = os.stat(infile)
        outfile_s = os.stat(outfile)
        return infile_s.st_mtime > outfile_s.st_mtime
    except:
        return True

def compile_files(options):
    # Compile all ui and resource files

    # check to see if we have pyuic4
    pyuic4 = check_path('pyuic4')

    if not pyuic4:
        print("pyuic4 is not in your path---unable to compile your ui files")
    else:
        ui_files = glob.glob('{}/*.ui'.format(options.plugin.gui_dir))
        ui_count = 0
        for ui in ui_files:
            if os.path.exists(ui):
                (base, ext) = os.path.splitext(ui)
                output = "{0}.py".format(base)
                if file_changed(ui, output):
                    print("Compiling {0} to {1}".format(ui, output))
                    subprocess.check_call([pyuic4, '-o', output, ui])
                    ui_count += 1
                else:
                    print("Skipping {0} (unchanged)".format(ui))
            else:
                print("{0} does not exist---skipped".format(ui))
        print("Compiled {0} UI files".format(ui_count))

    # check to see if we have pyrcc4
    pyrcc4 = check_path('pyrcc4')
    if not pyrcc4:
        print("pyrcc4 is not in your path---unable to compile your resource file(s)")
    else:
        res_files = options.plugin.resource_files
        res_count = 0
        for res in res_files:
            if os.path.exists(res):
                (base, ext) = os.path.splitext(res)
                output = "{0}.py".format(base)
                if file_changed(res, output):
                    print("Compiling {0} to {1}".format(res, output))
                    subprocess.check_call([pyrcc4, '-o', output, res])
                    res_count += 1
                else:
                    print("Skipping {0} (unchanged)".format(res))
            else:
                print("{0} does not exist---skipped".format(res))
        print("Compiled {0} resource files".format(res_count))

@task
def update_transifex(options):
    print("Updating transifex...")
    sh("sphinx-intl update-txconfig-resources --pot-dir {docroot}/i18n/pot --transifex-project-name {transifex_name}".format(docroot=options.sphinx.docroot, transifex_name=options.sphinx.transifex_name))

@task
@cmdopts([
    ('language=', 'l', 'language'),
])
def pretranslate(options):
    gettext(options)
    if not options.get('language', False):
        options.language = options.sphinx.language
    print("Generating the pot files for the LDMP toolbox help files.")
    sh("sphinx-intl --config {sourcedir}/conf.py update -p {docroot}/i18n/pot -l {lang}".format(sourcedir=options.sphinx.sourcedir,
        docroot=options.sphinx.docroot, lang=options.language))

@task
@cmdopts([
    ('language=', 'l', 'language'),
])
def gettext(options):
    if not options.get('language', False):
        options.language = options.sphinx.language
    SPHINX_OPTS = '-D language={lang} -A language={lang} {sourcedir}'.format(lang=options.language,
            sourcedir=options.sphinx.sourcedir)
    I18N_SPHINX_OPTS = '{sphinx_opts} {docroot}/i18n/pot'.format(docroot=options.sphinx.docroot, sphinx_opts=SPHINX_OPTS)
    sh("sphinx-build -b gettext -a {i18n_sphinx_opts}".format(i18n_sphinx_opts=I18N_SPHINX_OPTS))

@task
@cmdopts([
    ('clean', 'c', 'clean out built artifacts first'),
    ('ignore_errors', 'i', 'ignore documentation errors'),
    ('language=', 'l', 'language'),
])
def builddocs(options):
    if options.get('clean', False):
        options.sphinx.builddir.rmtree()
    if not options.get('language', False):
        options.language = options.sphinx.language

    SPHINX_OPTS = '-D language={lang} -A language={lang} {sourcedir}'.format(lang=options.language,
            sourcedir=options.sphinx.sourcedir)

    ignore_errors = options.get('ignore_errors', False)

    _localize_resources(options)

    sh("sphinx-intl --config {sourcedir}/conf.py build --language={lang}".format(sourcedir=options.sphinx.sourcedir,
        lang=options.language))

    # Build HTML docs
    if options.language != 'en' or ignore_errors:
        sh("sphinx-build -b html -a {sphinx_opts} {builddir}/html/{lang}".format(sphinx_opts=SPHINX_OPTS,
            builddir=options.sphinx.builddir, lang=options.language))
    else:
        sh("sphinx-build -n -W -b html -a {sphinx_opts} {builddir}/html/{lang}".format(sphinx_opts=SPHINX_OPTS,
            builddir=options.sphinx.builddir, lang=options.language))
    print("HTML Build finished. The HTML pages for '{lang}' are in {builddir}.".format(lang=options.language, builddir=options.sphinx.builddir))

    # Build PDF
    # sh("sphinx-build -b rinoh -a {sphinx_opts} {builddir}/pdf/{lang}".format(sphinx_opts=SPHINX_OPTS,
    #     sourcedir=options.sphinx.sourcedir, builddir=options.sphinx.builddir,
    #     lang=options.language))

def _localize_resources(options):
    print("Removing all static content from {sourcedir}/static.".format(sourcedir=options.sphinx.sourcedir))
    if os.path.exists('{sourcedir}/static'.format(sourcedir=options.sphinx.sourcedir)):
        rmtree('{sourcedir}/static'.format(sourcedir=options.sphinx.sourcedir))
    print("Copy 'en' (base) static content to {sourcedir}/static.".format(sourcedir=options.sphinx.sourcedir))
    if os.path.exists("{resourcedir}/en".format(resourcedir=options.sphinx.resourcedir)):
        shutil.copytree('{resourcedir}/en'.format(resourcedir=options.sphinx.resourcedir),
                        '{sourcedir}/static'.format(sourcedir=options.sphinx.sourcedir))
    print("Copy localized '{lang}' static content to {sourcedir}/static.".format(lang=options.language, sourcedir=options.sphinx.sourcedir))
    if options.language != 'en' and os.path.exists("{resourcedir}/{lang}".format(resourcedir=options.sphinx.resourcedir, lang=options.language)):
        src = '{resourcedir}/{lang}'.format(resourcedir=options.sphinx.resourcedir, lang=options.language)
        dst = '{sourcedir}/static'.format(sourcedir=options.sphinx.sourcedir)
        for item in os.listdir(src):
            s = os.path.join(src, item)
            d = os.path.join(dst, item)
            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
