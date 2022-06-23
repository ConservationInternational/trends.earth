.. _des_rpt:

Designing Reports
=================

Reports are, in simplest terms, created by populating a report template with textual and/or
spatial data from one or more jobs. It is important to note that reports are generated at the layer/band level
hence the number of reports from a single job will correspond to the number of **default** bands for the given
job.

Designing reports is a two-step process that involves:

1. Designing templates using the QGIS layout framework;
2. Specifying the configuration parameters in a report configuration file.

Prerequisites
_____________
Before embarking on designing new or customizing existing reports, it is recommended to familiarize
with the following topics:

* `QGIS Expression Framework <https://docs.qgis.org/3.16/en/docs/user_manual/working_with_vector/expression.html>`_
* `QGIS Layout Framework <https://docs.qgis.org/3.16/en/docs/user_manual/print_composer/index.html>`_
* `JSON Data Format <https://developer.mozilla.org/en-US/docs/Learn/JavaScript/Objects/JSON>`_


.. _layout_expr_vars:

Layout Expression Variables
___________________________
A report is made up of static content (such as logos, disclaimer text etc.) that does
not change from one report to another. It may also include dynamic content (such as maps or attribute information)
that is generated at runtime during the execution process.

The Trends.Earth toolbox provides a number of layout expression variables that can be used to insert dynamic
content in a layout. Some of these are available at design time while others are only available at runtime.
The table below provides a summary of the available variables.

Job Variables
~~~~~~~~~~~~~
These are characterized by a `te_job_` prefix and only available at runtime.

+----------------------+--------------------------------------------------------------------+---------------------------------+
| Variable Name        | Description                                                        | Data Type                       |
+======================+====================================================================+=================================+
| `te_job_id`          | Unique identified corresponding to the job's UUID                  | String                          |
+----------------------+--------------------------------------------------------------------+---------------------------------+
| `te_job_input_params`| JSON representation of a job's input parameters                    | String                          |
+----------------------+--------------------------------------------------------------------+---------------------------------+
| `te_job_paths`       | Local path to the job's dataset(s)                                 | String                          |
+----------------------+--------------------------------------------------------------------+---------------------------------+
| `te_job_alg_name`    | Job's algorithm name                                               | String                          |
+----------------------+--------------------------------------------------------------------+---------------------------------+
|`te_job_creation_date`| Creation date/time of a job                                        | String in %Y-%m-%d %H:%M format |
+----------------------+--------------------------------------------------------------------+---------------------------------+
| `te_job_status`      | Completion status of a job e.g. DOWNLOADED, GENERATED_LOCALLY etc. | String                          |
+----------------------+--------------------------------------------------------------------+---------------------------------+
| `te_job_name`        | Name of the job as inputted by the user.                           | String                          |
+----------------------+--------------------------------------------------------------------+---------------------------------+
| `te_job_comments`    | Comments to a job as provided by the user                          | String                          |
+----------------------+--------------------------------------------------------------------+---------------------------------+

Layer Variables
~~~~~~~~~~~~~~~
These are characterized by a `te_current_layer_` prefix and only available at runtime.

+-------------------------+----------------------------------------------------+-----------+
| Variable Name           | Description                                        | Data Type |
+=========================+====================================================+===========+
| `te_current_layer_name` | Name of the layer in the current execution context | String    |
+-------------------------+----------------------------------------------------+-----------+

Report Settings Variables
~~~~~~~~~~~~~~~~~~~~~~~~~
These are characterized by a `te_report_` prefix and are available at both design time and runtime. Refer to the
:ref:`report_settings` section for a detailed description of the report settings and corresponding variable names.

Template Types
______________
There are two main report template types:

Full Template
~~~~~~~~~~~~~
This is designed to contain - or provide an allowance to include - more information such as author name. The default
template is set on an A4 page and includes a layout title, map, legend, scale bar, north arrow, disclaimer text.
and logo.

Simple Template
~~~~~~~~~~~~~~~
This is designed to be a lighter version of the template with the default one set on an 83mm by 59mm page
size (in landscape mode) or vice versa in portrait mode and contains a map, legend, north arrow, scale bar, disclaimer
text and logo.

.. note::
    For each template type, you will need to provide both the portrait and landscape versions as the toolbox will select one of
    these depending on the dimensions of the map layer being rendered.

Designing Report Templates
__________________________
You can create templates either by:

Creating A New One
~~~~~~~~~~~~~~~~~~
1. Navigate to **Project > New Print Layout...**.

   .. image:: ../../../resources/en/documentation/reporting_tool/report_new_layout.png
      :align: center


2. Specify a user-friendly name for the layout.

   .. image:: ../../../resources/en/documentation/reporting_tool/report_template_name.png
      :align: center


Modifying an Existing One
~~~~~~~~~~~~~~~~~~~~~~~~~
1. Navigate to **Project > Layout Manager...**.

   .. image:: ../../../resources/en/documentation/reporting_tool/report_project_layout_manager.png
      :align: center


2. Select **Specific** in the drop-down menu under **New from Template** section.

   .. image:: ../../../resources/en/documentation/reporting_tool/report_layout_manager_specific.png
     :align: center


3. Click on the browse button (with three dots) to select an existing qpt template. The default templates can be found in `[base_data_directory]/reports/templates`.

   .. image:: ../../../resources/en/documentation/reporting_tool/report_layout_manager_browse.png
      :align: center


4. Click on **Create...** button.

   .. image:: ../../../resources/en/documentation/reporting_tool/report_layout_manager_create.png
      :align: center


5. Specify a user-friendly name for the template.

   .. image:: ../../../resources/en/documentation/reporting_tool/report_template_name.png
      :align: center


.. _adding_layout_items:

Adding Layout Items
~~~~~~~~~~~~~~~~~~~
* You can add items to the template in a similar fashion as defined in the `QGIS manual <https://docs.qgis.org/3.16/en/docs/user_manual/print_composer/composer_items/index.html>`_. Trends.Earth expression variables are available in
  the **Expression Builder** dialog and can be inserted in label items as any other QGIS variable.

  .. image:: ../../../resources/en/documentation/reporting_tool/report_expression_builder.png
     :align: center


* For instance, to insert a job's algorithm name in a label item, you can use the following expression: :code:`[% @te_job_alg_name %]`.

  .. image:: ../../../resources/en/documentation/reporting_tool/report_label_expression.png
   :align: center


* For a map item, do not add any layers or specify a map theme as the layers and their ordering will be automatically set during
  the report generation process.

* When using a legend item, ensure the **Auto update** option is selected. The toolbox will determine which legend
  items to show/hide depending on the rendering context.

  .. image:: ../../../resources/en/documentation/reporting_tool/report_legend_auto_update.png
   :align: center


* For map items rendering a job's layers or label items that use the toolbox's expression variables, please ensure
  that you define their corresponding item IDs so that they can be flagged for updating during the report generation
  process. A preferred naming convention - for the item ID - is `[item_type.context_name]` e.g. :code:`label.layer_name`,
  :code:`label.job_alg_name`, :code:`map.main`. We will see how these item IDs are used in the :ref:`item_scope_mapping`
  section.

  .. image:: ../../../resources/en/documentation/reporting_tool/report_item_id.png
   :align: center


.. _config_report_params:

Configuring Report Parameters
_____________________________
The next step is to define which templates will be used for which algorithms. This is done through a report
configuration file -`templates.json`- that is created in `[base_data_directory]/reports/templates` on loading the
toolbox for the first time.

`templates.json` is a list of report configuration objects where each configuration object corresponds to one or
more scopes. A scope, in this case, refers to an algorithm. A configuration is made up of two parts:

* **template_info** - Contains information about the QGIS report templates associated with one or more algorithm scopes.
* **output_options** - Output options for exporting a report.

See sample below:

.. code-block:: json

    {
      "template_info":{
         "id":"70ca4be7-839e-4248-be14-34ba8665ed98",
         "name":"Land Productivity",
         "description":"Overview of land productivity indicator.",
         "simple_portrait_path":"simple_layout_template_portrait.qpt",
         "simple_landscape_path":"simple_layout_template_landscape.qpt",
         "full_portrait_path":"full_layout_template_portrait.qpt",
         "full_landscape_path":"full_layout_template_landscape.qpt",
         "item_scopes":[
            {
               "name":"productivity",
               "type_id_mapping":{
                  "map":["map.main"],
                  "label":["label.layer_title"]
               }
            }
         ]
      },
      "output_options":{
         "template_type": "ALL",
         "formats": [
            {
               "format_type": "PDF"
            },
            {
               "format_type": "IMAGE",
               "params": {
                  "image_type": "png"
               }
            }
         ]
      }
   }

.. _template_info:

template_info
~~~~~~~~~~~~~
Contains information about the QGIS report templates associated with one or more algorithm scopes.

+-------------------------+---------------------------------------------------------------------------------+----------+
| Property Name           | Description                                                                     | Required |
+=========================+=================================================================================+==========+
| `id`                    | A unique UUID identifier in string format                                       | Yes      |
+-------------------------+---------------------------------------------------------------------------------+----------+
| `name`                  | A friendly name of the template configuration                                   | No       |
+-------------------------+---------------------------------------------------------------------------------+----------+
| `description`           | A brief description of the template configuration                               | No       |
+-------------------------+---------------------------------------------------------------------------------+----------+
| `simple_portrait_path`  | Name of the template file for a simple portrait layout                          | Yes      |
+-------------------------+---------------------------------------------------------------------------------+----------+
| `simple_landscape_path` | Name of the template file for a simple landscape layout                         | Yes      |
+-------------------------+---------------------------------------------------------------------------------+----------+
| `full_portrait_path`    | Name of the template file for a full portrait layout                            | Yes      |
+-------------------------+---------------------------------------------------------------------------------+----------+
| `full_landscape_path`   | Name of the template file for a full landscape layout                           | Yes      |
+-------------------------+---------------------------------------------------------------------------------+----------+
| `item_scopes`           | A list of item scope objects. It should contain at least one scope definition.  | Yes      |
|                         |                                                                                 |          |
|                         | See :ref:`item_scope_mapping` for more information.                             |          |
+-------------------------+---------------------------------------------------------------------------------+----------+


.. note::
    The paths defined above are basically file names which are relative to the location of the `templates.json` configuration
    file.


.. _output_options:

output_options
~~~~~~~~~~~~~~
Options for exporting an output report.

+-----------------+-----------------------------------------------------------------+----------+
| Property Name   | Description                                                     | Required |
+=================+=================================================================+==========+
| `formats`       | A list of format objects specifying the output format           | Yes      |
|                 | of the report. You can have a report produced in                |          |
|                 | multiple types such as PDF and PNG.                             |          |
|                 |                                                                 |          |
|                 | At least one output format needs to be defined.                 |          |
|                 |                                                                 |          |
|                 | See :ref:`output_format` for configuration options for          |          |
|                 | an output format object.                                        |          |
+-----------------+-----------------------------------------------------------------+----------+
| `template_type` | Report template type in string format.                          | Yes      |
|                 |                                                                 |          |
|                 | Supported options include: **SIMPLE**, **FULL** or **ALL**.     |          |
|                 |                                                                 |          |
|                 | Please note that these should be in uppercase as provided above.|          |
+-----------------+-----------------------------------------------------------------+----------+

.. _item_scope_mapping:

item_scope_mapping
~~~~~~~~~~~~~~~~~~
Provides a mechanism for grouping layout items based on a scope (i.e. algorithm).

+-------------------+----------------------------------------------------------------------------------+----------+
| Property Name     | Description                                                                      | Required |
+===================+==================================================================================+==========+
| `name`            | Name of the algorithm that will be matched to this configuration                 | Yes      |
|                   | e.g. `productivity`, `sdg-15-3-1-sub-indicators` etc. Refers to the algorithm    |          |
|                   | names defined in `scripts.json` in the toolbox's data folder.                    |          |
+-------------------+----------------------------------------------------------------------------------+----------+
| `type_id_mapping` | A dictionary containing an enumeration of the layout item type and corresponding | Yes      |
|                   | list of item IDs defined in the template.                                        |          |
|                   |                                                                                  |          |
|                   | Supported layout item types include: **map**, **label**, **picture**             |          |
|                   |                                                                                  |          |
|                   | .. code-block:: json                                                             |          |
|                   |                                                                                  |          |
|                   |     "type_id_mapping":{                                                          |          |
|                   |        "map":["map.main"],                                                       |          |
|                   |        "label":["label.layer_title"]                                             |          |
|                   |     }                                                                            |          |
|                   |                                                                                  |          |
|                   |                                                                                  |          |
|                   | See :ref:`adding_layout_items` on how to specify item IDs.                       |          |
+-------------------+----------------------------------------------------------------------------------+----------+

.. _output_format:

output_format
~~~~~~~~~~~~~
Format information for the report output.

+---------------+----------------------------------------------------------------+----------+
| Property Name | Description                                                    | Required |
+===============+================================================================+==========+
| `format_type` | An enumeration of the file output type.                        | Yes      |
|               |                                                                |          |
|               | Supported enumeration options include: **PDF** and **IMAGE**.  |          |
|               |                                                                |          |
|               | Please note that these should be in uppercase as provided      |          |
|               | above.                                                         |          |
+---------------+----------------------------------------------------------------+----------+
| `params`      | Depending on the specified output type, this property contains | No       |
|               | additional information regarding the format.                   |          |
|               |                                                                |          |
|               | For instance, if the IMAGE is specified as the output format,  |          |
|               | then this property can be used to specify the IMAGE type. Does |          |
|               | nothing for PDF type and defaults to PNG for an IMAGE type.    |          |
+---------------+----------------------------------------------------------------+----------+


Resetting to Default Templates and Configuration
_______________________________________________________
To revert back to the default templates and report configuration file that ship with the toolbox, perform the following steps:

1. Close QGIS then back-up the `templates` folder in `[base_data_directory]/reports/templates`.

2. Proceed to delete the `templates` folder then restart QGIS.

