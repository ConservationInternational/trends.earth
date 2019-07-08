Frequently asked questions
==========================

This page lists some Frequently Asked Questions (FAQs) for the |trends.earth|
tool.

General Questions
_________________

**How do I find more information on the project?**

More information on the toolbox can be found at `trends.earth 
<http://trends.earth>`_ and reports are available on the `Vital Signs Project 
website <http://vitalsigns.org/gef-ldmp/project-description-and-timeline>`_ You 
can also add your contact info at `Vital Signs LD Email Distribution List 
<http://vitalsigns.org/gef-ldmp/email-distribution-list>`_ to stay in touch 
with any advancements with the projects’ distrubtion list.

**How can I provide feedback on the tool?**

There are three ways to give feedback, emailing the project team, visiting the 
project site and messaging through the anonymous form or rate the toolbox in 
the plugins menu of QGIS. The project technical team can address questions 
through trends.earth@conservation.org. Users can rate the toolbox by opening 
Plugins in QGIS and selecting Manage and Install Plugins. Select All in the 
side bar and navigate to trends.earth plugin. Click on trends.earth and rate 
the toolbox by selecting the number of stars you would like to give the plugin, 
5 stars being highly satisfied.

Installation of Trends.Earth
____________________________


**What version of Quantum GIS (QGIS) do I need for the toolbox?**

To download QGIS, please go to the QGIS Downloads page. As of February 2018, 
version 3.0 was released. Please use version 2.18 for the trends.earth plugin. 
A version compatible with the latest version will be released in future 
iterations of the project.

**Do I need to download a 32-bit or 64 bit version of QGIS?**

We recommend downloading 64-bit version (2.18), but you may need to download 
the 32-bit version for 32-bit operating systems. To find out if your computer 
is running a 32-bit or 64-bit version of Windows,  search for System or 
msinfo32. This is found in the Control Panel and will bring up a window that 
says the system type e.g. System type: 64-bit Operating System, x64-based 
processor. 

Windows 7 or Windows Vista:

#. Open System by clicking the Start button , right-clicking Computer, and then 
   clicking Properties.
#. Under System, you can view the system type.

Windows 8 or Windows 10:

#. From the Start screen, type This PC.
#. Right Click (or tap and hold) This PC, and click Properties.

Mac:

#. Click the Apple icon in the top left and select "About this Mac".
#. For more advanced details click "More Info..." in the About This Mac window.

**How do I install the plugin?**

Open QGIS, navigate to Plugins on the menu bar, and select Manage and install 
plugins. On the side menu, select All to view the plugins available in QGIS. 
Search for trends.earth and select Install plugin at the bottom of the window.

**How do I upgrade the plugin?**

If you have already installed the plugin, navigate to Plugins on the menu bar, 
and select Manage and install plugins. On the side menu, select Installed to 
view the plugins that you have installed in your computer. At the bottom of the 
window, select Upgrade all to upgrade the toolbox to the latest version.

Datasets
________

**When will you update datasets for the current year?**

Trends.Earth uses publicly available data, as such the most up to date datasets 
will be added to the toolbox as soon as the original data providers make them 
public. If you notice any update that we missed, please do let us know.

**Is there an option to download the original data?**

Users can download the original data using the Download option within the 
toolbox.

**Will the toolbox support higher resolution datasets?**

The toolbox currently supports AVHRR (8km) and MODIS (250m) data for primary 
productivity analysis, and ESA LCC CCI (300m) for land cover change analysis.

**Can the toolbox support analysis with national-level datasets?**

This is a common request from users, and one the team is working on. 
Trends.Earth will allow loading of national-level soil carbon and land cover 
datasets before the end of March, 2018. This will allow users to take advantage 
of existing datasets that might be of higher quality at a national-level than 
the global datasets that are the defaults in the tool.

Methods
_______

**Who was the default time period for the analysis determined?**

The default time period of analysis is from years 2001 to 2015. These were 
recommended by the `Good Practice Guidelines 
<http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_., 
a document that provides detailed recommendations for measuring land 
degradation and has been adopted by the UNCCD.

Productivity
~~~~~~~~~~~~

**How does the result provided by state differs from trajectory?**

The trajectory analysis uses linear regressions and non-parametric tests to 
identify long term significant trends in primary productivity. This method 
however, is not able to capture more recent changes in primary productivity, 
which could be signals of short term processes of improvement or degradation. 
By comparing a long term mean to the most recent period, state is able to 
capture such recent changes.
 

Land cover
~~~~~~~~~~

**Currently, the land cover aggregation is done following the UNCCD guidelines, 
but that classification does not take into account country level 
characteristics. Could it be possible to allow the user to define the 
aggregation criteria?**

Users are able to make these changes using the advanced settings in the land 
cover GUI so that appropriate aggregations occur depending on the context of 
your country.

**How can we isolate woody plant encroachment within the toolbox?**

This can be altered using the land cover change matrix in the toolbox. For 
every transition, the user can mark the change as stable, improvement or 
degraded. The transition from grassland/rangeland to shrubland may indicate 
woody encroachment and this transition can be marked as an indicator of 
degradation.

Carbon stocks
~~~~~~~~~~~~~

**Why use soil organic carbon (SOC) instead of above and below-ground carbon to 
measure carbon stocks?**

The original proposed indicator is Carbon Stocks, which would include above and 
below ground biomass. However, given the lack of consistently generated and 
comparable dataset which assess carbon stocks in woody plants (including 
shrubs), grasses, croplands, and other land cover types both above and below 
ground, the `Good Practice Guidelines 
<http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_ 
published by the UNCCD recommends for the time being to use SOC as a proxy.

**Is it possible to measure identify processes of degradation linked to 
salinization using this tool?**

Not directly. If salinization caused a reduction in primary productivity, that 
decrease would be identified by the productivity indicators, but the users 
would have to use their local knowledge to assign the causes.

Land degradation outputs
________________________

**How were the layers combined to define the final land degradation layer?**

Performance, state, and trajectory (the three indicators of change in 
productivity_) are combined following a modified version of the good practice 
guidance developed by the UNCCD (in section SDG Indicator 15.3.1 of this manual 
a table is presented). Productivity, soil carbon, and land cover chance (the 
three sub-indicators of SDG 15.3.1) are combined using a “one out, all out” 
principle. In other words: if there is a decline in any of the three indicators 
at a particular pixel, then that pixel is mapped as being “degraded”.

**Why do I see areas improving (in green) or degrading (in red) after the final 
analysis when I know they are not?**

The final output should be interpreted as showing areas potentially degraded. 
The indicator of land degradation is based on changes in productivity, land 
cover and soil organic carbon. Several factor could lead to the identification 
of patterns of degradation which do not seem to correlate to what is happening 
on the ground, the date of analysis being a very important one. If the climatic 
conditions at the beginning of the analysis were particularly wet, for example, 
trends from that moment on could show significant decreases in primary 
productivity, and degradation. The user can use Trends.Earth to address some of 
this issues correcting by the effect of climate. The resolution of the data 
could potentially be another limitation. Trends.Earth by default uses global 
datasets which will not be the most relevant at all scales and geographies. A 
functionality to use local data will be added shortly.

**All of the sub-indicators are measuring vegetation using three different 
methods: how does this contribute to understanding and identifying land 
degradation?**

Vegetation is a key component of most ecosystems, and serve as a good proxy for 
their overall functioning and health. The three subindicators used for SDG 
15.3.1 measure different aspects of land cover, which do relate to vegetation. 
Primary productivity directly measures the change in amount of biomass present 
in one area, but it does not inform us if that change is positive or not (not 
all increases in plant biomass should be interpreted as improvement). Land 
cover fills that gap by interpreting the landscape from a thematic perspective 
looking at what was there before and what is there now. It does include 
vegetation, but also bare land, urban and water. Finally, the soil organic 
carbon indicator uses the land cover map to inform the changes in soil organic 
carbon over time. This method is not ideal, but given the current state of 
global soil science and surveying, there is consensus that it this point in 
time and globally, this is the best approach.

Workshops
_________

**Will the project offer future training opportunities so users can continues working with the tool?**

The project is working with the UNCCD to support their work training users on 
monitoring and reporting in support of countries’ national-level 
responsibilities under the convention. These trainings will be occurring in 
March-April 2018. In addition, the project will work with key stakeholders, 
such as RCMRD, to provide support through existing platforms. The project will 
also continue to make e-learning materials available to users, and is 
considering potential funding sources for further capacity-building activities 
in East Africa.

Future plans
____________

**When will there be an offline version of the toolbox?**

The final toolbox will be available as both as an offline and online version. 
The online version allows users to access current datasets more easily, while 
also allowing users to leverage Google Earth Engine to provide computing in the 
cloud. An offline version allows users to access data and perform analyses 
where internet connectivity may be limited, but it does have the disadvantage 
of requiring users to have enough local computing capacity to run analyses 
locally. The technical team intends to build the offline version of the toolbox 
and provide countries with data relevant for reporting at the national level 
within the pilot project countries. 

**Will you create a trends.earth toolbox for ESRI users?**

The toolbox is currently available as a plugin to QGIS, an open source software 
package. This allows users around the world free access to the toolbox. There 
are currently no plans to build a toolbox within ArcGIS or ArcPro. 

