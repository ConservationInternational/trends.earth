# -*- coding: utf-8 -*-
#
# LDMP documentation build configuration file, created by
# sphinx-quickstart on Sun Feb 12 17:11:03 2012.
#
# This file is execfile()d with the current directory set to its containing dir.
#
# Note that not all possible configuration values are present in this
# autogenerated file.
#
# All configuration values have a default; values that are commented out
# serve to show the default.

import sys
import os
import sphinx_rtd_theme

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#sys.path.insert(0, os.path.abspath('.'))

# -- General configuration -----------------------------------------------------

# If your documentation needs a minimal Sphinx version, state it here.
#needs_sphinx = '1.0'

# Add any Sphinx extension module names here, as strings. They can be extensions
# coming with Sphinx (named 'sphinx.ext.*') or your custom ones.
#extensions = ['sphinx.ext.todo', 'sphinx.ext.viewcode', 'rinoh.frontend.sphinx']
#extensions = ['sphinx.ext.todo', 'sphinx.ext.viewcode', 'rst2pdf.pdfbuilder']
extensions = ['sphinx.ext.todo', 'sphinx.ext.viewcode']

todo_include_todos=True

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# The suffix of source filenames.
source_suffix = '.rst'

# The encoding of source files.
#source_encoding = 'utf-8-sig'

# The master toctree document.
master_doc = 'index'

# General information about the project.
project = u'Trends.Earth'
copyright = u'2018, Conservation International'

locale_dirs = ['../i18n/']
gettext_compact = False

# The version info for the project you're documenting, acts as replacement for
# |version| and |release|, also used in various other places throughout the
# built documents.
#
# The short X.Y version.
version = '1.0.3'
# The full version, including alpha/beta/rc tags.
release = '1.0.3'

rst_epilog = """
.. |iconCalculator| image:: /static/common/icon-calculator.png
   :width: 2em
.. |iconChart| image:: /static/common/icon-chart.png
   :width: 2em
.. |iconClipboard| image:: /static/common/icon-clipboard.png
   :width: 2em
.. |iconCloudDownload| image:: /static/common/icon-cloud-download.png
   :width: 2em
.. |iconCog| image:: /static/common/icon-cog.png
   :width: 2em
.. |iconGlobe| image:: /static/common/icon-globe.png
   :width: 2em
.. |iconGraph| image:: /static/common/icon-graph.png
   :width: 2em
.. |iconInfo| image:: /static/common/icon-info.png
   :width: 2em
.. |iconMarkMarker| image:: /static/common/icon-map-marker.png
   :width: 2em
.. |iconWrench| image:: /static/common/icon-wrench.png
   :width: 2em
.. |iconFolder| image:: /static/common/icon-folder.png
   :width: 2em
.. |iconVisualization| image:: /static/common/icon-reporting.png
   :width: 2em
.. |trends.earth| image:: /static/common/trends_earth_logo_bl_print.png
   :width: 7em
   :alt: Trends.Earth
.. |logoCI| image:: /static/common/logo_CI_square.png
    :width: 150
    :target: http://www.conservation.org
.. |logoLund| image:: /static/common/logo_Lund_square.png
    :width: 125
    :target: http://www.lunduniversity.lu.se
.. |logoNASA| image:: /static/common/logo_NASA_square.png
    :width: 125
    :target: http://www.nasa.gov
.. |logoGEF| image:: /static/common/logo_GEF.png
    :width: 125
    :target: https://www.thegef.org
.. |CURRENT| replace:: {current_version}
.. |qgisMinVersion| replace:: 3.10.3
""".format(current_version=version)

# The language for content autogenerated by Sphinx. Refer to documentation
# for a list of supported languages.
language = 'en'

# There are two options for replacing |today|: either, you set today to some
# non-false value, then it is used:
#today = ''
# Else, today_fmt is used as the format for a strftime call.
#today_fmt = '%B %d, %Y'

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
exclude_patterns = ["../resources"]

# The reST default role (used for this markup: `text`) to use for all documents.
#default_role = None

# If true, '()' will be appended to :func: etc. cross-reference text.
#add_function_parentheses = True

# If true, the current module name will be prepended to all description
# unit titles (such as .. function::).
#add_TemplateModuleNames = True

# If true, sectionauthor and moduleauthor directives will be shown in the
# output. They are ignored by default.
#show_authors = False

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = 'sphinx'

# A list of ignored prefixes for module index sorting.
#modindex_common_prefix = []

# -- Options for HTML output ---------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
html_theme = "sphinx_rtd_theme"

# Theme options are theme-specific and customize the look and feel of a theme
# further.  For a list of options available for each theme, see the
# documentation.
#html_theme_options = {}

# Add any paths that contain custom themes here, relative to this directory.
html_theme_path = [sphinx_rtd_theme.get_html_theme_path()]

# The name for this set of Sphinx documents.  If None, it defaults to
# "<project> v<release> documentation".
#html_title = None

# A shorter title for the navigation bar.  Default is the same as html_title.
#html_short_title = None

# The name of an image file (relative to this directory) to place at the top
# of the sidebar.
#html_logo = '../resources/en/common/trends_earth_logo_bl_1200.png'
html_logo = '../resources/en/common/trends_earth_logo_square_32x32.ico'

# The name of an image file (within the static path) to use as favicon of the
# docs.  This file should be a Windows icon file (.ico) being 16x16 or 32x32
# pixels large.
html_favicon = '../resources/en/common/trends_earth_logo_square_32x32.ico'

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['static']

html_show_sourcelink = False

# Note the underscore SHOULD be used below as this is how the static folder is
# named by sphinx on generation.
html_context = {
    'css_files': ['_static/custom.css'],
}

# If not '', a 'Last updated on:' timestamp is inserted at every page bottom,
# using the given strftime format.
#html_last_updated_fmt = '%b %d, %Y'

# If true, SmartyPants will be used to convert quotes and dashes to
# typographically correct entities.
#html_use_smartypants = True

# Custom sidebar templates, maps document names to template names.
#html_sidebars = {}

# Additional templates that should be rendered to pages, maps page names to
# template names.
#html_additional_pages = {}

# If false, no module index is generated.
#html_domain_indices = True

# If false, no index is generated.
#html_use_index = True

# If true, the index is split into individual pages for each letter.
#html_split_index = False

# If true, links to the reST sources are added to the pages.
#html_show_sourcelink = True

# If true, "Created using Sphinx" is shown in the HTML footer. Default is True.
#html_show_sphinx = True

# If true, "(C) Copyright ..." is shown in the HTML footer. Default is True.
#html_show_copyright = True

# If true, an OpenSearch description file will be output, and all pages will
# contain a <link> tag referring to it.  The value of this option must be the
# base URL from which the finished HTML is served.
#html_use_opensearch = ''

# This is the file name suffix for HTML files (e.g. ".xhtml").
#html_file_suffix = None

# Output file base name for HTML help builder.
htmlhelp_basename = 'TemplateClassdoc'

# -- Options for LaTeX output --------------------------------------------------

latex_documents = [
    ('index', u'Trends.Earth.tex', u'Trends.Earth Documentation', u'Conservation International', 'manual'),
    ('training/tutorial_installation', u'Trends.Earth_Tutorial01_Installation.tex', u'Installation', u'Conservation International', 'howto'),
    ('training/tutorial_run_all_subindicators', u'Trends.Earth_Tutorial02_Computing_Indicators.tex', u'Compute Sub-indicators', u'Conservation International', 'howto'),
    ('training/tutorial_task_download', u'Trends.Earth_Tutorial03_Downloading_Results.tex', u'Downloading Results', u'Conservation International', 'howto'),
    ('training/tutorial_custom_lpd', u'Trends.Earth_Tutorial04_Using_Custom_Productivity.tex', u'Using Custom Land Productivity Data', u'Conservation International', 'howto'),
    ('training/tutorial_custom_landcover', u'Trends.Earth_Tutorial05_Using_Custom_Land_Cover.tex', u'Using Custom Land Cover Data', u'Conservation International', 'howto'),
    ('training/tutorial_custom_soc', u'Trends.Earth_Tutorial06_Using_Custom_Soil_Carbon.tex', u'Using Custom Soil Organic Carbon Data', u'Conservation International', 'howto'),
    ('training/tutorial_compute_sdg_indicator', u'Trends.Earth_Tutorial07_Computing_SDG_Indicator.tex', u'How to Compute the SDG Indicator', u'Conservation International', 'howto'),
    ('training/tutorial_summary_table', u'Trends.Earth_Tutorial08_The_Summary_Table.tex', u'The Summary Table', u'Conservation International', 'howto'),
    ('training/tutorial_load_basemap', u'Trends.Earth_Tutorial09_Loading_a_Basemap.tex', u'Loading a Basemap', u'Conservation International', 'howto'),
    ('training/tutorial_forest_carbon', u'Trends.Earth_Tutorial10_Forest_Carbon.tex', u'Forest and Carbon Change Tool', u'Conservation International', 'howto'),
    ('training/tutorial_compute_urban_indicator', u'Trends.Earth_Tutorial11_Urban_Change_SDG_Indicator.tex', u'Urban Change SDG 11.3.1', u'Conservation International', 'howto'),
]

latex_elements = {
    # The paper size ('letterpaper' or 'a4paper').
    'papersize': 'a4paper',
    'preamble': u'''\\usepackage{fontspec}
                    \\setmainfont{lmroman10-regular.otf}''',
}

# The name of an image file (relative to this directory) to place at the top of
# the title page.
latex_logo = '../resources/en/common/trends_earth_logo_bl_1200.png'

# For "manual" documents, if this is true, then toplevel headings are parts,
# not chapters.
#latex_use_parts = False

# If true, show page references after internal links.
#latex_show_pagerefs = False

# If true, show URL addresses after external links.
#latex_show_urls = False

# Documents to append as an appendix to all manuals.
#latex_appendices = []

# If false, no module index is generated.
#latex_domain_indices = True


# -- Options for manual page output --------------------------------------------

# One entry per manual page. List of tuples
# (source start file, name, description, authors, manual section).
man_pages = [
    ('index', 'TemplateClass', u'trends.earth documentation',
     [u'Conservation International'], 1)
]
