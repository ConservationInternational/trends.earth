.. _faq:

Frequently asked questions
==========================

This page lists some Frequently Asked Questions (FAQs) for the |trends.earth| tool.

General Questions
_________________

Is there a user group I can share experiences with and learn from?
------------------------------------------------------------------

Yes, we recently created a `Google group for Trends.Earth users 
<https://groups.google.com/forum/#!forum/trends_earth_users>`_ so please `join 
<https://groups.google.com/forum/#!forum/trends_earth_users/join>`_ and participate! 
We aim for this group to be a forum for users to post questions about the tool, 
methods, and datasets in support of Sustainable Development Goals monitoring. 
The |trends.earth| team will monitor the group and answer questions as needed, 
but we'll get the most out of this community if users support each other by 
answering questions based on their unique background and experiences. The group 
will also be used for announcements on tool updates and capacity building 
efforts.

How do I find more information on the project?
------------------------------------------------------------------

More information on the toolbox can be found at `trends.earth 
<http://trends.earth>`_ and reports are available on the `Vital Signs Project 
website <http://vitalsigns.org/gef-ldmp/project-description-and-timeline>`_ You 
can also add your contact info at `Vital Signs LD Email Distribution List 
<http://vitalsigns.org/gef-ldmp/email-distribution-list>`_ to stay in touch 
with any advancements with the projects’ distrubtion list.

How can I provide feedback on the tool?
------------------------------------------------------------------

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


What version of Quantum GIS (QGIS) do I need for the toolbox?
------------------------------------------------------------------

To download QGIS, please go to the QGIS Downloads page. As of February 2018, 
version 3.0 was released. Please use version 2.18 for the trends.earth plugin. 
A version compatible with the latest version will be released in future 
iterations of the project.

Do I need to download a 32-bit or 64 bit version of QGIS?
------------------------------------------------------------------

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

How do I install the plugin?
------------------------------------------------------------------

Open QGIS, navigate to Plugins on the menu bar, and select Manage and install 
plugins. On the side menu, select All to view the plugins available in QGIS. 
Search for trends.earth and select Install plugin at the bottom of the window.

How do I upgrade the plugin?
------------------------------------------------------------------

If you have already installed the plugin, navigate to Plugins on the menu bar, 
and select Manage and install plugins. On the side menu, select Installed to 
view the plugins that you have installed in your computer. At the bottom of the 
window, select Upgrade all to upgrade the toolbox to the latest version.

How do I uninstall the plugin?
------------------------------------------------------------------

If you would like to uninstall the plugin, normally you can do so with the QGIS 
plugins manager. To access the tool, choose "Plugins" and then "Manage and 
Install Plugins..." from the QGIS menu bar. From the plugin manager screen, 
select "Installed" from the menu on the left-hand side. Then click on 
"Trends.Earth" in the list of plugins, and on "Uninstall Plugin" to uninstall 
it.

If you encounter an error uninstalling the plugin, it is also possible to 
remove it manually. To manually remove the plugin:

#. Open QGIS
#. Navigate to where the plugin is installed by selecting "Open Active Profile 
   Folder" from the menu under "Settings" - "User Profiles" on the menu bar.
#. Quit QGIS. You may not be able to uninstall the plugin if QGIS is not 
   closed.
#. In the file browser window that opened, double click on "python", and then 
   double click on "plugins". Delete the LDMP folder within that directory.
#. Restart QGIS.

OR

Navigate to the AppData folder under user account and find the plugins info 
under the directory. For example:
C:\Documents\user\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins

Datasets
________

.. note::
    Refer to the :ref:`data_sources` section for more information on data sources used in Trends.Earth.
	
When will you update datasets for the current year?
------------------------------------------------------------------

Trends.Earth uses publicly available data, as such the most up to date datasets 
will be added to the toolbox as soon as the original data providers make them 
public. If you notice any update that we missed, please do let us know.

Is there an option to download the original data?
------------------------------------------------------------------

Users can download the original data using the Download option within the 
toolbox.

Will the toolbox support higher resolution datasets?
------------------------------------------------------------------

The toolbox currently supports AVHRR (8km) and MODIS (250m) data for primary 
productivity analysis, and ESA LCC CCI (300m) for land cover change analysis.

Can the toolbox support analysis with national-level datasets?
------------------------------------------------------------------

This is a common request from users, and one the team is working on. 
Trends.Earth will allow loading of national-level soil carbon and land cover 
datasets before the end of March, 2018. This will allow users to take advantage 
of existing datasets that might be of higher quality at a national-level than 
the global datasets that are the defaults in the tool.

Methods
_______

.. note::
    Refer to the :ref:`background_landdegradation` section for more background on analyses available in Trends.Earth.

Who was the default time period for the analysis determined?
------------------------------------------------------------------

The default time period of analysis is from years 2001 to 2015. These were 
recommended by the `Good Practice Guidelines 
<http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_., 
a document that provides detailed recommendations for measuring land 
degradation and has been adopted by the UNCCD.

Productivity
------------------------------------------------------------------

How does the result provided by state differs from trajectory?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The trajectory analysis uses linear regressions and non-parametric tests to 
identify long term significant trends in primary productivity. This method 
however, is not able to capture more recent changes in primary productivity, 
which could be signals of short term processes of improvement or degradation. 
By comparing a long term mean to the most recent period, state is able to 
capture such recent changes.
 

Land cover
------------------------------------------------------------------

Currently, the land cover aggregation is done following the UNCCD guidelines, but that classification does not take into account country level characteristics. Could it be possible to allow the user to define the aggregation criteria?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Users are able to make these changes using the advanced settings in the land 
cover GUI so that appropriate aggregations occur depending on the context of 
your country.

How can we isolate woody plant encroachment within the toolbox?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This can be altered using the land cover change matrix in the toolbox. For 
every transition, the user can mark the change as stable, improvement or 
degraded. The transition from grassland/rangeland to shrubland may indicate 
woody encroachment and this transition can be marked as an indicator of 
degradation.

Carbon stocks
------------------------------------------------------------------

Why use soil organic carbon (SOC) instead of above and below-ground carbon to  measure carbon stocks?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The original proposed indicator is Carbon Stocks, which would include above and 
below ground biomass. However, given the lack of consistently generated and 
comparable dataset which assess carbon stocks in woody plants (including 
shrubs), grasses, croplands, and other land cover types both above and below 
ground, the `Good Practice Guidelines 
<http://www2.unccd.int/sites/default/files/relevant-links/2017-10/Good%20Practice%20Guidance_SDG%20Indicator%2015.3.1_Version%201.0.pdf>`_ 
published by the UNCCD recommends for the time being to use SOC as a proxy.

Is it possible to measure identify processes of degradation linked to salinization using this tool?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Not directly. If salinization caused a reduction in primary productivity, that 
decrease would be identified by the productivity indicators, but the users 
would have to use their local knowledge to assign the causes.

Land degradation outputs
________________________

How were the layers combined to define the final land degradation layer?
---------------------------------------------------------------------------

Performance, state, and trajectory (the three indicators of change in 
productivity_) are combined following a modified version of the good practice 
guidance developed by the UNCCD (in section SDG Indicator 15.3.1 of this manual 
a table is presented). Productivity, soil carbon, and land cover chance (the 
three sub-indicators of SDG 15.3.1) are combined using a “one out, all out” 
principle. In other words: if there is a decline in any of the three indicators 
at a particular pixel, then that pixel is mapped as being “degraded”.

Why do I see areas the data says are improving or degrading when I know they are not?
-------------------------------------------------------------------------------------

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

All of the sub-indicators are measuring vegetation: how does this contribute to understanding and identifying land degradation?
--------------------------------------------------------------------------------------------------------------------------------

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

Future plans
____________

When will there be an offline version of the toolbox?
------------------------------------------------------------------

The final toolbox will be available as both as an offline and online version. 
The online version allows users to access current datasets more easily, while 
also allowing users to leverage Google Earth Engine to provide computing in the 
cloud. An offline version allows users to access data and perform analyses 
where internet connectivity may be limited, but it does have the disadvantage 
of requiring users to have enough local computing capacity to run analyses 
locally. The technical team intends to build the offline version of the toolbox 
and provide countries with data relevant for reporting at the national level 
within the pilot project countries. 

Will you create a trends.earth toolbox for ESRI users?
------------------------------------------------------------------

The toolbox is currently available as a plugin to QGIS, an open source software 
package. This allows users around the world free access to the toolbox. There 
are currently no plans to build a toolbox within ArcGIS or ArcPro. 

.. _pubs:

Publications
===================

The below publications either use or relate to |trends.earth|.

* Alamanos, A. and Linnane, S., 2021. Estimating SDG Indicators in Data-Scarce Areas: 
  The Transition to the Use of New Technologies and Multidisciplinary Studies. Earth, 2(3), pp.635-652.
* Dong, J., Metternicht, G., Hostert, P., Fensholt, R., Chowdhury, R.R., 2019.
  Remote sensing and geospatial technologies in support of a normative land system
  science: status and prospects. Curr. Opin. Environ. Sustain. 38, 44–52.
  https://doi.org/10.1016/j.cosust.2019.05.003
* Easdale, M.H., Fariña, C., Hara, S., Pérez León, N., Umaña, F., Tittonell, P., Bruzzone,
  O., 2019. Trend-cycles of vegetation dynamics as a tool for land degradation
  assessment and monitoring. Ecol. Indic. 107, 105545. https://doi.org/10.1016/j.ecolind.2019.105545
* Giuliani, G., Chatenoux, B., Benvenuti, A., Lacroix, P., Santoro, M., Mazzetti, P., 2020a. 
  Monitoring land degradation at national level using satellite Earth Observation time-series data to 
  support SDG15 – exploring the potential of data cube. Big Earth Data 4, 3–22. 
  https://doi.org/10.1080/20964471.2020.1711633
* Giuliani, G., Mazzetti, P., Santoro, M., Nativi, S., Van Bemmelen, J., Colangeli, G., Lehmann, A., 2020b. 
  Knowledge generation using satellite earth observations to support sustainable development goals (SDG): 
  A use case on Land degradation. Int. J. Appl. Earth Obs. Geoinformation 88, 102068. 
  https://doi.org/10.1016/j.jag.2020.102068
* Gonzalez-Roglich, M., Zvoleff, A., Noon, M., Liniger, H., Fleiner, R., Harari, N., Garcia,
  C., 2019. Synergizing global tools to monitor progress towards land degradation neutrality:
  Trends.Earth and the World Overview of Conservation Approaches and Technologies sustainable
  land management database. Environ. Sci. Policy 93, 34–42. 
  https://doi.org/10.1016/j.envsci.2018.12.019
* Jiang, L., Bao, A., Jiapaer, G., Liu, R., Yuan, Y. and Yu, T., 2022. Monitoring land degradation and assessing its drivers 
  to support sustainable development goal 15.3 in Central Asia. Science of The Total Environment, 807, p.150868.
  https://doi.org/10.1016/j.scitotenv.2021.150868
* Kadaverugu, A., Nageshwar Rao, C. and Viswanadh, G.K., 2021. Quantification of flood mitigation services by urban green spaces using InVEST model: 
  a case study of Hyderabad city, India. Modeling Earth Systems and Environment, 7(1), pp.589-602.
  https://doi.org/10.1007/s40808-020-00937-0
* Kust, G.S., Andreeva, O.V., Lobkovskiy, V.A., 2020. Land Degradation Neutrality: the Modern Approach to Research
  on Arid Regions at the National Level. Arid Ecosyst. 10, 87–92.
  https://doi.org/10.1134/S2079096120020092 
* Hu, Y., Wang, C., Yu, X. and Yin, S., 2021. Evaluating Trends of Land Productivity Change and Their Causes in 
  the Han River Basin, China: In Support of SDG Indicator 15.3. 1. Sustainability, 13(24), p.13664.
  https://doi.org/10.3390/su132413664
* Li, Z., Lun, F., Liu, M., Xiao, X., Wang, C., Wang, L., Xu, Y., Qi, W., Sun, D., 2021. Rapid diagnosis of 
  agricultural soil health: A novel soil health index based on natural soil productivity and human management.
  J. Environ. Manage. 277, 111402. 
  https://doi.org/10.1016/j.jenvman.2020.111402
* Liniger, H., Harari, N., van Lynden, G., Fleiner, R., de Leeuw, J., Bai, Z.,
  Critchley, W., 2019. Achieving land degradation neutrality: The role of SLM
  knowledge in evidence-based decision-making. Environ. Sci. Policy 94, 123–134.
  https://doi.org/10.1016/j.envsci.2019.01.001
* Mariathasan, V., Bezuidenhoudt, E., Olympio, K.R., 2019. 
  Evaluation of Earth Observation Solutions for Namibia’s SDG Monitoring System. Remote Sens. 11, 1612. 
  https://doi.org/10.3390/rs11131612
* Mazzetti, P., Nativi, S., Santoro, M., Giuliani, G., Rodila, D., Folino, A., Caruso, S., Aracri, G. and Lehmann, A., 2022. 
  Knowledge formalization for Earth Science informed decision-making: The GEOEssential Knowledge Base. 
  Environmental Science & Policy, 131, pp.93-104.
  https://doi.org/10.1016/j.envsci.2021.12.023
* Meyer, D. & Riechert, M. Open source QGIS toolkit for the Advanced Research 
  WRF modelling system. Environmental Modelling & Software 112, 166–178 (2019). 
  https://doi.org/10.1016/j.envsoft.2018.10.018
* Moussa, S., El Brirchi, E.H. and Alami, O.B., 2022. Monitoring Land Productivity Trends in Souss-Massa Region Using Landsat 
  Time Series Data to Support SDG Target 15.3. In Geospatial Intelligence (pp. 119-129). Springer, Cham.
  https://doi.org/10.1007/978-3-030-80458-9_9
* Ogorodnikov, S.S., 2021, March. Land Degradation Neutrality in the Tula region. In IOP Conference Series: 
  Earth and Environmental Science (Vol. 723, No. 4, p. 042053). IOP Publishing.
  doi:10.1088/1755-1315/723/4/042053
* Prakash, M., Ramage, S., Kavvada, A., Goodman, S., 2020. 
  Open Earth Observations for Sustainable Urban Development. Remote Sens. 12, 1646. 
  https://doi.org/10.3390/rs12101646
* Philip, E., 2021. Coupling Sustainable Development Goal 11.3. 1 with current planning tools: city of Hamilton, Canada. 
  Hydrological Sciences Journal, 66(7), pp.1124-1131.
  https://doi.org/10.1080/02626667.2021.1918340
* Reith, J., Ghazaryan, G., Muthoni, F. and Dubovyk, O., 2021. Assessment of Land Degradation in Semiarid Tanzania—Using Multiscale Remote Sensing Datasets 
  to Support Sustainable Development Goal 15.3. Remote Sensing, 13(9), p.1754.
  https://doi.org/10.3390/rs13091754
* Rowe, H.I., Gruber, D. and Fastiggi, M., 2021. Where to start? A new citizen science, remote sensing approach to map recreational 
  disturbance and other degraded areas for restoration planning. Restoration Ecology, 29(6), p.e13454.
  https://doi.org/10.1111/rec.13454
* Schiavina, M., Melchiorri, M., Freire, S., Florio, P., Ehrlich, D., Tommasi, P., Pesaresi, M. and Kemper, T., 2022. 
  Land use efficiency of functional urban areas: Global pattern and evolution of development trajectories. 
  Habitat International, 123, p.102543.
  https://doi.org/10.1016/j.habitatint.2022.102543
* Sims, N. C. et al. Developing good practice guidance for estimating land 
  degradation in the context of the United Nations Sustainable Development 
  Goals. Environmental Science & Policy 92, 349–355 (2019). 
  https://doi.org/10.1016/j.envsci.2018.10.014
* Teich, I., Gonzalez Roglich, M., Corso, M.L., García, C.L., 2019. 
  Combining Earth Observations, Cloud Computing, and Expert Knowledge to Inform National Level 
  Degradation Assessments in Support of the 2030 Development Agenda. Remote Sens. 11, 2918. 
  https://doi.org/10.3390/rs11242918
* Timm Hoffman, M., Skowno, A., Bell, W. & Mashele, S. Long-term changes in 
  land use, land cover and vegetation in the Karoo drylands of South Africa: 
  implications for degradation monitoring. African Journal of Range & Forage 
  Science 35, 209–221 (2018). 
  https://doi.org/10.2989/10220119.2018.1516237
* Trifonova, T.A., Mishchenko, N.V., Shutov, P.S. et al. Estimation of the Dynamics of Production Processes 
  in Landscapes of the South Taiga Subzone of the Eastern European Plain by Remote Sensing Data. 
  Moscow Univ. Soil Sci. Bull. 76, 11–18 (2021). 
  https://doi.org/10.3103/S0147687421010063
* Venter, Z.S., Scott, S.L., Desmet, P.G., Hoffman, M.T., 2020. 
  Application of Landsat-derived vegetation trends over South Africa: Potential for monitoring land 
  degradation and restoration. Ecol. Indic. 113, 106206. 
  https://doi.org/10.1016/j.ecolind.2020.106206
* von Maltitz, G.P., Gambiza, J., Kellner, K., Rambau, T., Lindeque, L., Kgope, B., 2019. 
  Experiences from the South African land degradation neutrality target setting process. 
  Environ. Sci. Policy 101, 54–62. 
  https://doi.org/10.1016/j.envsci.2019.07.003

.. _other_resources:
  
Other resources
===============

Print documentation from the Trends.Earth project (including fact sheets, 
reports, and other materials) is listed below.

.. _reports:

Reports
________

- `A Review of Publicly Available Geospatial Datasets and Indicators In Support of Land Degradation Monitoring
  <https://static1.squarespace.com/static/5dffad039a288739c6ae0b85/t/61e6ee8f42b6c16e2cb538cf/1642524304092/ci-6-Tools4LDN-report-FNL+web.pdf>`_
- `A Review of Publicly Available Geospatial Datasets and Indicators in Support of Drought Monitoring
  <https://static1.squarespace.com/static/5dffad039a288739c6ae0b85/t/6033f28abca1996aedc492d5/1614017200233/ci-4-Tools4LDN2-FNL+web.pdf>`_
- `A Review of Publicly Available Geospatial Datasets and Indicators in Support of UNCCD Strategic Objective (SO) 2:
  To Improve Living Conditions of Populations Affected by Desertification, Land Degradation, and Drought
  <https://static1.squarespace.com/static/5dffad039a288739c6ae0b85/t/60abf26cb4223a6ade81cecd/1621881469733/ci-3-Tools4LDN-3+%281%29.pdf>`_
- `Trends in Population Exposure to Land Degradation - Methodological note 
  <https://www.unccd.int/sites/default/files/inline-files/MethodologicalNote_PopExposureToLD.pdf>`_
- `Arnold S., Jun C., Olav E. 2019. Global and Complementary (Non-authoritative)
  Geospatial Data for SDGs: Role and Utilisation. Report produced jointly by the Task
  Team on Global Data and Task Team on Alternative Data Sources by the Working Group
  on Geospatial Information of the Inter-agency and Expert Group on Sustainable Development
  Goal Indicators (IAEG-SDGs).
  <http://ggim.un.org/documents/Report_Global_and_Complementary_Geospatial_Data_for_SDGs.pdf>`_
- `Using Spectral Vegetation Indices to Measure Gross Primary Productivity as 
  an Indicator of Land Degradation 
  <http://vitalsigns.org/sites/default/files/VS_GEFLDMP_Report1_C1_R3_WEB_HR.pdf>`_
- `Evaluation of approaches for incorporating higher-resolution data for 
  disaggregation or targeted analysis 
  <http://vitalsigns.org/sites/default/files/CI_GEF_Report%202_C1_R1_PRINT.pdf>`_
- `Disentangling the effects of climate and land use on land degradation 
  <http://vitalsigns.org/sites/default/files/CI_GEF_Report%205_C1_R1_PRINT.pdf>`_
- `Monitoring and assessing land degradation to support sustainable development 
  <http://vitalsigns.org/sites/default/files/CI_GEF_Guidance%20ENG_C1_R1_PRINT%20%281%29.pdf>`_ 
- `(French) Suivre et évaluer la dégradation des terres pour soutenir le développement 
  durable  
  <http://vitalsigns.org/sites/default/files/CI_GEF_Guidance%20FRE_C1_R1_PRINT%20%281%29.pdf>`_

.. _fact_sheets:

Fact sheets
___________

- `Conceptual Fact Sheet for Trends.Earth 
  <http://trends.earth/docs/en/_static/common/Trends.Earth_Fact_Sheet.pdf>`_
- `Technical Fact Sheet for Trends.Earth 
  <http://trends.earth/docs/en/_static/common/Trends.Earth_Fact_Sheet_Technical.pdf>`_
  

.. _academic_dissertations:

Academic dissertations
________________________

- Mahlaba, B., 2022. The assessment of degradation state in Ecological Infrastructure and prioritisation for rehabilitation 
  and drought mitigation in the Tsitsa River Catchment (Masters dissertation, Rhodes University).
- Owuor, G.O., 2021. Monitoring Land Degradation Neutrality using Geospatial Techniques in Support of Sustainable Land Management: 
  A Case Study of Narok County (Doctoral dissertation, University of Nairobi).