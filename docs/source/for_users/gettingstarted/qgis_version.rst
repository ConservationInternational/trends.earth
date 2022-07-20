.. _qgis_instructions:

Installing Trends.Earth
========================

.. _install_qgis:
   
QGIS installation
-----------------

Before installing the plugin, QGIS version |qgisMinVersion| or higher
needs to be installed on your computer.

Download QGIS
~~~~~~~~~~~~~~

To install the plugin, you must have QGIS version |qgisMinVersion| or higher. Download
the appropriate installer depending on your operating system:

   * Windows: `Download Windows installer from here 
     <https://qgis.org/en/site/forusers/download.html#windows>`_.

   * MacOS: `Download MacOS installer from here 
     <https://qgis.org/en/site/forusers/download.html#mac>`_.

   * Linux: `Download Linux installer from here, or from the repository for 
     your Linux distribution 
     <https://qgis.org/en/site/forusers/download.html#linux>`_.

Install QGIS
~~~~~~~~~~~~~~~~~~~~~~~

Once the installer is downloaded from the website, it needs to be run (double 
click on it). Select the Default settings for all options.

Installing older versions of QGIS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Older versions of QGIS can be accessed at the below links. We recommend the 
latest version of QGIS (see instructions above) but the below links might be 
useful if you have a specific need for accessing an older version of QGIS
(for example if you need to install an older version of |trends.earth|).

* Windows: `Download older versions of QGIS for Windows here
  <https://qgis.org/downloads/>`_.

* MacOS: `Download older versions of QGIS for MacOS here 
  <https://qgis.org/downloads/macOS>`_.

.. _install_toolbox:

Trends.Earth installation
-------------------------

There are different ways to install |trends.earth|, depending on whether you want 
to install the stable version (recommended) or the development version.

Installing the stable version (recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The preferred way to install the |trends.earth| is through QGIS. To install from 
within QGIS, first launch QGIS, and then go to `Plugins` in the menu bar at the 
top of the program and select `Manage and install plugins`. 

.. image:: ../../../resources/en/documentation/installing/plugin_menu.png
   :align: center

Then search for a plugin called `trends.earth` and select `Install plugin` at 
the bottom right of the screen.

.. image:: ../../../resources/en/documentation/installing/plugin_box_install_plugin.png
   :align: center

If your plugin has been installed properly, there will be a menu bar in the top 
left of your browser that looks like this:

.. image:: ../../../resources/en/common/icon-trends_earth.png
   :align: center

If problems arise during installation
+++++++++++++++++++++++++++++++++++++

If you encounter any issues when installing or upgrading the plugin, we recommend you
try the following before contacting the developers of |Trends.Earth|:

* Try restarting QGIS after installing or upgrading the plugin - this can solve many
  common installation issues.

* If you are having a problem upgrading the plugin, try uninstalling the old version of
  Trends.Earth before installing the new one. This can be done from within the
  `Installed tab of the plugins
  window <(https://docs.qgis.org/3.22/en/docs/user_manual/plugins/plugins.html#the-installed-tab>`_.

If the above don't work, please contact us at trends.earth@conservation.org.

Installing the development version (advanced users)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

There are two ways to install the development version of the plugin. For more 
details, see the `README 
<https://github.com/ConservationInternational/trends.earth#development-version>`_ 
for |trends.earth|.

.. toctree::
   :maxdepth: 2

.. _registration:

Trends.Earth registration
--------------------------


1. To Register, click the **Register for Trends.Earth (step 1)** button from the "Settings" dialog box under **Trends.Earth login information**.   
   
.. image:: ../../../resources/en/documentation/settings/settings_highlight_register.png
   :align: center

2. Enter your email, name, organization and country of residence.

.. image:: ../../../resources/en/documentation/settings/register_new_user_dialog.png
   :align: center

3. Select **Ok** and you will see a message indicating your user has been registered.

.. image:: ../../../resources/en/documentation/settings/registration_success.png
   :align: center

4. After registering, you will receive an email from api@trends.earth with your password. If you don't see the email in your inbox after 15-20 seconds, 
please check your spam folder in case the email was sent there. Once you receive this email , click on the "Edit selected configuration" icon in the "Settings" dialog: 

.. image:: ../../../resources/en/documentation/settings/settings_dialog_highlight_edit_selected_configuration.png
   :align: center

5. This will bring up the "Authentication" dialog asking for your password. Enter the password you received from api@trends.earth and click "Save":

.. image:: ../../../resources/en/documentation/settings/authenication_dialog.png
   :align: center

6. From the "Settings" dialog  click on "Test connection": 

.. image:: ../../../resources/en/documentation/settings/settings_dialog_highlight_test_connection.png
   :align: center

7. You will see a message indicating you have successfully been logged in:

.. image:: ../../../resources/en/documentation/settings/login_success.png
   :align: center

You are now ready to start using Trends.Earth!   
