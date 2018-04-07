# -*- coding: utf-8 -*-
import os
import sys
import fnmatch
import glob
import re
import mimetypes
import json
import stat
import shutil
import subprocess
from tempfile import mkstemp
from multiprocessing.pool import ThreadPool
import zipfile

import boto3

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
        translations = ['fr', 'es', 'pt', 'sw', 'ar', 'ru', 'zh'],
        resource_files = [path('LDMP/resources.qrc')],
        package_dir = path('build'),
        tests = ['test'],
        excludes = [
            'LDMP/test',
            'LDMP/data_prep_scripts',
            'LDMP/help',
            'gee',
            'util',
            '*.pyc',
        ],
        # skip certain files inadvertently found by exclude pattern globbing
        skip_exclude = []
    ),

    schemas = Bunch(
        setup_dir = path('LDMP/schemas'),
    ),

    gee = Bunch(
        tecli = path('C:/Users/azvol/Code/LandDegradation/trends.earth-CLI/tecli'),
        script_dir = path('gee'),
    ),

    sphinx = Bunch(
        docroot = path('LDMP/help'),
        sourcedir = path('LDMP/help/source'),
        builddir = path('LDMP/help/build'),
        resourcedir = path('LDMP/help/resources'),
        deploy_s3_bucket = 'trends.earth',
        docs_s3_prefix = 'docs/',
        transifex_name = 'land_degradation_monitoring_toolbox_docs_1_0',
        base_language = 'en',
        latex_documents = ['Trends.Earth.tex',
                           'Trends.Earth_Tutorial01_Installation.tex',
                           'Trends.Earth_Tutorial02_Computing_Indicators.tex',
                           'Trends.Earth_Tutorial03_Downloading_Results.tex',
						   'Trends.Earth_Tutorial04_Using_Custom_Productivity.tex',
						   'Trends.Earth_Tutorial05_Using_Custom_Land_Cover.tex',
						   'Trends.Earth_Tutorial06_Using_Custom_Soil_Carbon.tex',
                           'Trends.Earth_Tutorial07_Computing_SDG_Indicator.tex',
                           'Trends.Earth_Tutorial08_The_Summary_Table.tex',
                           'Trends.Earth_Tutorial09_Loading_a_Basemap.tex']
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


# Function to find and replace in a file
def _replace(file_path, regex, subst):
    #Create temp file
    fh, abs_path = mkstemp()
    with os.fdopen(fh,'wb') as new_file:
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
    v = getattr(options, 'version', False)
    # Validate the version matches the regex
    if not v or not re.match("[0-9]+([.][0-9]+)+", v):
        print('Must specify a valid version (example: 0.36)')
        return
     
    # Set in Sphinx docs in make.conf
    print('Setting version to {} in sphinx conf.py'.format(v))
    sphinx_regex = re.compile("(((version)|(release)) = ')[0-9]+([.][0-9]+)+", re.IGNORECASE)
    _replace(os.path.join(options.sphinx.sourcedir, 'conf.py'), sphinx_regex, '\g<1>' + v)

    # Set in metadata.txt
    print('Setting version to {} in metadata.txt'.format(v))
    sphinx_regex = re.compile("^(version=)[0-9]+([.][0-9]+)+")
    _replace(os.path.join(options.source_dir, 'metadata.txt'), sphinx_regex, '\g<1>' + v)
    
    # Set in __init__.py
    print('Setting version to {} in __init__.py'.format(v))
    init_regex = re.compile('^(__version__[ ]*=[ ]*["\'])[0-9]+([.][0-9]+)+')
    _replace(os.path.join(options.source_dir, '__init__.py'), init_regex, '\g<1>' + v)

    # For the GEE config files the version can't have a dot, so convert to 
    # underscore
    v_gee = v.replace('.', '_')
    if not v or not re.match("[0-9]+(_[0-9]+)+", v_gee):
        print('Must specify a valid version (example: 0.36)')
        return

    gee_id_regex = re.compile('(, )?"id": "[0-9a-z-]*"(, )?')
    gee_script_name_regex = re.compile('("name": "[0-9a-zA-Z -]*)( [0-9]+(_[0-9]+)+)?"')

    # Set version for GEE scripts
    for subdir, dirs, files in os.walk(options.gee.script_dir):
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
    _replace(os.path.join(options.source_dir, 'data', 'scripts.json'), scripts_regex, '\g<1>' + v)

    # Set in setup.py
    print('Setting version to {} in trends.earth-schemas setup.py'.format(v))
    setup_regex = re.compile("^([ ]*version=[ ]*')[0-9]+([.][0-9]+)+")
    _replace(os.path.join(options.schemas.setup_dir, 'setup.py'), setup_regex, '\g<1>' + v)


@task
def publish_gee(options):
    dirs = next(os.walk(options.gee.script_dir))[1]
    for dir in dirs:
        script_dir = os.path.join(options.gee.script_dir, dir) 
        if os.path.exists(os.path.join(script_dir, 'configuration.json')):
            print('Publishing {}...'.format(dir))
            subprocess.check_call(['python',
                                   options.gee.tecli,
                                   'publish', '--public=True', '--overwrite=True'], cwd=script_dir)

@task
@cmdopts([
    ('clean', 'c', 'Clean out dependencies first'),
])
def setup(options):
    '''install dependencies'''
    clean = getattr(options, 'clean', False)
    ext_libs = options.plugin.ext_libs
    ext_src = options.plugin.ext_src
    if clean:
        ext_libs.rmtree()
    ext_libs.makedirs()
    runtime, test = read_requirements()

    try:
        import pip
    except:
        error('FATAL: Unable to import pip, please install it first!')
        sys.exit(1)

    os.environ['PYTHONPATH']=str(ext_libs.abspath())
    for req in runtime + test:
        # Don't install numpy with pyqtgraph - QGIS already has numpy. So use 
        # the --no-deps flag (-N for short) with that package only.
        if 'pyqtgraph' in req:
            pip.main(['install',
                      '--upgrade',
                      '--no-deps',
                      '-t',
                      ext_libs.abspath(),
                      req])
        else:
            pip.main(['install',
                      '--upgrade',
                      '-t',
                      ext_libs.abspath(),
                      req])


@task
def translate(options):
    lrelease = check_path('lrelease')
    if not lrelease:
        print("lrelease is not in your path---unable to release translation files")
    print("Pulling transifex translations...")
    subprocess.check_call(['tx', 'pull', '-f', '-s', '--parallel'])
    print("Releasing translations using lrelease...")
    for translation in options.plugin.translations:
        subprocess.check_call([lrelease, os.path.join(options.plugin.i18n_dir, 'LDMP_{}.ts'.format(translation))])

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
    compile_files(options)
    plugin_name = options.plugin.name
    src = path(__file__).dirname() / plugin_name
    dst_plugins = path('~').expanduser() / folder / 'python' / 'plugins'
    dst_this_plugin = dst_plugins / plugin_name
    src = src.abspath()
    dst_this_plugin = dst_this_plugin.abspath()
    if not hasattr(os, 'symlink') or (os.name == 'nt'):
        if not options.get('fast', False):
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
    ('fast', 'f', "don't run rmtree"),
])
def install(options):
    _install(".qgis2", options)

@task
@cmdopts([
    ('fast', 'f', "don't run rmtree"),
])
def installdev(options):
    _install(".qgis-dev", options)

@task
@cmdopts([
    ('fast', 'f', "don't run rmtree"),
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
    compile_files(options)
    tests = options.get('tests', False)
    package_dir = options.plugin.package_dir
    package_dir.makedirs()
    package_file =  package_dir / '{}.zip'.format(options.plugin.name)
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
])
def deploy(options):
    setup(options)
    package(options)
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
    package_file =  options.plugin.package_dir / '{}.zip'.format(options.plugin.name)
    data = open(package_file, 'rb')
    client.put_object(Key='sharing/LDMP.zip',
                      Body=data, 
                      Bucket=options.sphinx.deploy_s3_bucket)
    print('Package uploaded')


@task
@cmdopts([
    ('ignore_errors', 'i', 'ignore documentation errors'),
    ('language', 'l', "which language to build (all are built by default)"),
    ('fast', 'f', "don't build docs"),
])
def deploy_docs(options):
    if not options.get('fast', False):
        builddocs(options)

    try:
        with open(os.path.join(os.path.dirname(__file__), 'aws_credentials.json'), 'r') as fin:
            keys = json.load(fin)
        client = boto3.client('s3',
                              aws_access_key_id=keys['access_key_id'],
                              aws_secret_access_key=keys['secret_access_key'])
    except IOError:
        print('Warning: AWS credentials file not found. Credentials must be in environment variable.')
        client = boto3.client('s3')

    print('Clearing existing docs.')
    paginator = client.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=options.sphinx.deploy_s3_bucket,
                               Prefix='docs/')
    for page in pages:
        if page['KeyCount'] == 0:
            break
        objects = [{'Key': obj['Key']} for obj in page['Contents']]
        client.delete_objects(Bucket=options.sphinx.deploy_s3_bucket,
                              Delete={'Objects': objects})
    print('Existing docs in s3 bucket {} deleted.'.format(options.sphinx.deploy_s3_bucket))

    print('Uploading docs to S3.')
    filenames = [os.path.normpath(os.path.join(dp, f)) for dp, dn, fn in os.walk(options.sphinx.builddir, 'html') for f in fn]
    def upload(f):
        key = f[f.find('\html'):]
        key = key.replace('\\', '/')
        key = re.sub('^/html', 'docs', key)
        guessed_mime_type = mimetypes.guess_type(f)[0]
        if guessed_mime_type:
            extra_args = {'ContentType': guessed_mime_type}
        else:
            extra_args = {}
        client.put_object(Key=key,
                          Body=open(f, 'rb'), 
                          Bucket=options.sphinx.deploy_s3_bucket,
                          **extra_args)
    pool = ThreadPool(processes=20)
    pool.map(upload, filenames)
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
            #debug('Excluding {}'.format(itempath))
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
                    # Fix the links to c header files that Qt Designer adds to 
                    # UI files when QGIS custom widgets are used
                    ui_regex = re.compile("(<header>)qgs[a-z]*.h(</header>)", re.IGNORECASE)
                    _replace(ui, ui_regex, '\g<1>qgis.gui\g<2>')
                    print("Compiling {0} to {1}".format(ui, output))
                    subprocess.check_call([pyuic4, '-x', ui, '-o', output])
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
def pretranslate(options):
    gettext(options)
    print("Generating the pot files for the LDMP toolbox help files.")
    for translation in options.plugin.translations:
        sh("sphinx-intl --config {sourcedir}/conf.py update -p {docroot}/i18n/pot -l {lang}".format(sourcedir=options.sphinx.sourcedir,
            docroot=options.sphinx.docroot, lang=translation))

    pylupdate4 = check_path('pylupdate4')
    if not pylupdate4:
        print("pylupdate4 is not in your path---unable to gather strings for translation")
    print("Gathering strings for translation using pylupdate4")
    subprocess.check_call([pylupdate4, os.path.join(options.plugin.i18n_dir, 'i18n.pro')])
    subprocess.check_call('tx push --parallel -s')


@task
@cmdopts([
    ('language=', 'l', 'language'),
])
def gettext(options):
    if not options.get('language', False):
        language = options.sphinx.base_language
    SPHINX_OPTS = '-D language={lang} -A language={lang} {sourcedir}'.format(lang=language,
            sourcedir=options.sphinx.sourcedir)
    I18N_SPHINX_OPTS = '{sphinx_opts} {docroot}/i18n/pot'.format(docroot=options.sphinx.docroot, sphinx_opts=SPHINX_OPTS)
    sh("sphinx-build -b gettext -a {i18n_sphinx_opts}".format(i18n_sphinx_opts=I18N_SPHINX_OPTS))

@task
@cmdopts([
    ('clean', 'c', 'clean out built artifacts first'),
    ('ignore_errors', 'i', 'ignore documentation errors'),
    ('language=', 'l', "which language to build (all are built by default)"),
    ('fast', 'f', "only build english docs"),
])
def builddocs(options):
    if options.get('clean', False):
        options.sphinx.builddir.rmtree()

    if options.get('language', False):
        languages = [options.get('language')]
    else:
        languages = [options.sphinx.base_language]
        languages.extend(options.plugin.translations)

    for language in languages:
        print("\nBuilding {lang} documentation...".format(lang=language))
        SPHINX_OPTS = '-D language={lang} -A language={lang} {sourcedir}'.format(lang=language,
                sourcedir=options.sphinx.sourcedir)

        ignore_errors = options.get('ignore_errors', False)

        _localize_resources(options, language)

        sh("sphinx-intl --config {sourcedir}/conf.py build --language={lang}".format(sourcedir=options.sphinx.sourcedir,
            lang=language))

        # Build HTML docs
        if language != 'en' or ignore_errors:
            sh("sphinx-build -b html -a {sphinx_opts} {builddir}/html/{lang}".format(sphinx_opts=SPHINX_OPTS,
                builddir=options.sphinx.builddir, lang=language))
        else:
            sh("sphinx-build -n -W -b html -a {sphinx_opts} {builddir}/html/{lang}".format(sphinx_opts=SPHINX_OPTS,
                builddir=options.sphinx.builddir, lang=language))
        print("HTML Build finished. The HTML pages for '{lang}' are in {builddir}.".format(lang=language, builddir=options.sphinx.builddir))

        # Build PDF, by first making latex from sphinx, then pdf from that
        tex_dir = "{builddir}/latex/{lang}".format(builddir=options.sphinx.builddir, lang=language)
        sh("sphinx-build -b latex -a {sphinx_opts} {tex_dir}".format(sphinx_opts=SPHINX_OPTS, tex_dir=tex_dir))

        for doc in options.sphinx.latex_documents:
            for n in range(3):
                # Run multiple times to ensure crossreferences are right
                subprocess.check_call(['xelatex', doc], cwd=tex_dir)
            # Move the PDF to the html folder so it will be uploaded with the 
            # site
            doc_pdf = os.path.splitext(doc)[0] + '.pdf'
            out_dir = '{builddir}/html/{lang}/pdfs'.format(builddir=options.sphinx.builddir, lang=language)
            if not os.path.exists(out_dir):
                os.makedirs(out_dir)
            shutil.move('{tex_dir}/{doc}'.format(tex_dir=tex_dir, doc=doc_pdf),
                        '{out_dir}/{doc}'.format(out_dir=out_dir, doc=doc_pdf))

def _localize_resources(options, language):
    print("Removing all static content from {sourcedir}/static.".format(sourcedir=options.sphinx.sourcedir))
    if os.path.exists('{sourcedir}/static'.format(sourcedir=options.sphinx.sourcedir)):
        rmtree('{sourcedir}/static'.format(sourcedir=options.sphinx.sourcedir))
    print("Copy 'en' (base) static content to {sourcedir}/static.".format(sourcedir=options.sphinx.sourcedir))
    if os.path.exists("{resourcedir}/en".format(resourcedir=options.sphinx.resourcedir)):
        shutil.copytree('{resourcedir}/en'.format(resourcedir=options.sphinx.resourcedir),
                        '{sourcedir}/static'.format(sourcedir=options.sphinx.sourcedir))
    print("Copy localized '{lang}' static content to {sourcedir}/static.".format(lang=language, sourcedir=options.sphinx.sourcedir))
    if language != 'en' and os.path.exists("{resourcedir}/{lang}".format(resourcedir=options.sphinx.resourcedir, lang=language)):
        src = '{resourcedir}/{lang}'.format(resourcedir=options.sphinx.resourcedir, lang=language)
        dst = '{sourcedir}/static'.format(sourcedir=options.sphinx.sourcedir)
        for item in os.listdir(src):
            s = os.path.join(src, item)
            d = os.path.join(dst, item)
            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
