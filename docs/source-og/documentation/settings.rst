Registration and settings
=========================

.. image:: /static/common/ldmt_toolbar_highlight_settings.png
   :align: center

.. _registration:

Registration
------------

The toolbox is free to use, but you must register an email address prior to
using any of the cloud-based functions.

To register your email and obtain a free account, select the wrench
icon (|iconWrench|). This will open up the "Settings" dialog box:

.. image:: /static/documentation/settings/settings.png
   :align: center

To Register, click the "Step 1: Register" button. Enter your email, name,
organization and country of residence and select "Ok":

.. image:: /static/documentation/settings/registration.png
   :align: center

You will see a meesage indicating your user has been registered:

.. image:: /static/documentation/settings/registration_success.png
   :align: center

After registering, you will receive an email from api@trends.earth with your
password. Once you receive this email, click on "Step 2: Enter login". This
will bring up a dialog asking for your email and password. Enter the password
you received from api@trends.earth and click "Ok":

.. image:: /static/documentation/settings/login.png
   :align: center

You will see a message indicating you have successfully been logged in:

.. image:: /static/documentation/settings/login_success.png
   :align: center

Updating your user
------------------

If you already are registered for |Trends.Earth| but want to change your login
information; update your name, organization, or country; or delete your user,
click on "Update user" from the "Settings" dialog.

.. image:: /static/documentation/settings/settings_update.png
   :align: center

If you want to change your username, click on "Change user". Note that this
function is only useful if you already have another existing |trends.earth|
account you want to switch to. To register a new user, see :ref:`registration`.
To change your user, enter the email and password you wish to change to and
click "Ok":

.. image:: /static/documentation/settings/login.png
   :align: center

If you want to update your profile, click on "Update profile". Update your
information in the box that appears and click "Save":

.. image:: /static/documentation/settings/settings_update_details.png
   :align: center

To delete your user, click "Delete user". A warning message will appear. Click
"Ok" if you are sure you want to delete your user:

.. image:: /static/documentation/settings/delete_user.png
   :align: center


Forgot password
---------------

If you forget your password, click on "Reset password" from the settings dialog
box.

A password will be sent to your email. Please check your Junk folder if you
cannot find it within your inbox. The email will come from api@trends.earth.

Once you receive your new password, return to the "Settings" screen and use
"Step 2: Enter login" to enter your new pasword.

.. image:: /static/documentation/settings/forgot_password.png
   :align: center

Advanced settings
-----------------

Click "Edit advanced options" to bring up the advanced settings page:


.. image:: /static/documentation/settings/advanced.png
   :align: center


From the advanced settings page, you can change settings including
enabling/disabling debug mode, and loading pre-compiled binaries to speed up
calculations in Trends.Earth.


Debug mode
__________

Debug mode saves additional information on the processes that you run in
Trends.Earth to the QGIS messages log (accessible by enabling the "Log Messages
Panel" under "View" and then "Panels" on the QGIS menu bar).

To enable logging of debug messages, check the box. These messages may be
useful when trying to problem-solve any issues you might encounter while using
Trends.Earth.

Use binaries for faster processing
__________________________________

Some of the functions in Trends.Earth are available in versions that have been
compiled using the `Numba`_ library. Numba can translate Python code into
machine code (binaries), resulting in functions that run much faster. For users
of Trends.Earth, this means being able to process data more quickly than in the
standard version of Trends.Earth.

Because Numba is not supported within QGIS, and compiling files with Numba
requires having additional software installed on your machine, we have made
binaries available that you (optionally) download and use within Trends.Earth.
This is intended to make it easier for our users to access the benefits of
Numba without needing to install it themselves.

To access the binaries, first choose a folder on your machine where you would
like to have them saved, by clicking the "Browse" button on the advanced
settings screen. Once you have chosen a folder, click "Download" to download
the binaries to your machine. After downloading the binaries, restart QGIS in
order to enable them. Check the advanced settings page after restarting. If
they are working correctly, you will see a message saying "Binaries **are**
loaded". If you have any trouble enabling the binaries, reach out to the
`Trends.Earth discussion group
<https://groups.google.com/forum/#!forum/trends_earth_users/join>`_ for help.

.. note:: Not all of the functions in Trends.Earth can make use of the
   binaries, so don't expect everything to run faster after you have installed
   them. The summary tool for SDG 15.3.1, however, should run much faster after
   installing the binaries, particularly if you are working with very high
   resolution custom datasets. In the future we will be adding support for
   other functions as well.

.. _Numba: http://numba.pydata.org/
