<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis styleCategories="Fields|Forms" version="3.44.13-Solothurn">
  <fieldConfiguration>
    <field configurationFlags="NoFlag" name="GEF_CP_ID">
      <editWidget type="">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="NoFlag" name="Country">
      <editWidget type="">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="NoFlag" name="Site_ID">
      <editWidget type="">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="NoFlag" name="Date">
      <editWidget type="DateTime">
        <config>
          <Option type="Map">
            <Option type="bool" value="false" name="allow_null"/>
            <Option type="bool" value="true" name="calendar_popup"/>
            <Option type="QString" value="yyyy-MM-dd" name="display_format"/>
            <Option type="QString" value="yyyy-MM-dd" name="field_format"/>
          </Option>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="NoFlag" name="Indicator">
      <editWidget type="ValueMap">
        <config>
          <Option type="Map">
            <Option type="List" name="map">
              <Option type="Map">
                <Option type="QString" value="1. Under improved management" name="1. Under improved management"/>
              </Option>
              <Option type="Map">
                <Option type="QString" value="3. Under restoration" name="3. Under restoration"/>
              </Option>
              <Option type="Map">
                <Option type="QString" value="4. Under improved practices" name="4. Under improved practices"/>
              </Option>
            </Option>
          </Option>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="NoFlag" name="Sub_Indic">
      <editWidget type="ValueMap">
        <config>
          <Option type="Map">
            <Option type="List" name="map">
              <Option type="Map">
                <Option type="QString" value="1.1 Protected areas newly created" name="1.1 Protected areas newly created"/>
              </Option>
              <Option type="Map">
                <Option type="QString" value="1.2 Improved management effectiveness" name="1.2 Improved management effectiveness"/>
              </Option>
              <Option type="Map">
                <Option type="QString" value="3.1 Degraded agricultural lands" name="3.1 Degraded agricultural lands"/>
              </Option>
              <Option type="Map">
                <Option type="QString" value="3.2 Forest and forest land" name="3.2 Forest and forest land"/>
              </Option>
              <Option type="Map">
                <Option type="QString" value="3.3 Natural grasslands and woodlands" name="3.3 Natural grasslands and woodlands"/>
              </Option>
              <Option type="Map">
                <Option type="QString" value="3.4 Wetlands, estuaries and mangroves" name="3.4 Wetlands, estuaries and mangroves"/>
              </Option>
              <Option type="Map">
                <Option type="QString" value="4.1 Management benefiting biodiversity" name="4.1 Management benefiting biodiversity"/>
              </Option>
              <Option type="Map">
                <Option type="QString" value="4.2 Third-party certification" name="4.2 Third-party certification"/>
              </Option>
              <Option type="Map">
                <Option type="QString" value="4.3 Sustainable production systems" name="4.3 Sustainable production systems"/>
              </Option>
              <Option type="Map">
                <Option type="QString" value="4.4 HCV forest loss avoided" name="4.4 HCV forest loss avoided"/>
              </Option>
            </Option>
          </Option>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="NoFlag" name="Area_Type">
      <editWidget type="">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="NoFlag" name="Activity">
      <editWidget type="">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
    <field configurationFlags="NoFlag" name="Source">
      <editWidget type="">
        <config>
          <Option/>
        </config>
      </editWidget>
    </field>
  </fieldConfiguration>
  <aliases>
    <alias index="0" field="GEF_CP_ID" name=""/>
    <alias index="1" field="Country" name=""/>
    <alias index="2" field="Site_ID" name=""/>
    <alias index="3" field="Date" name=""/>
    <alias index="4" field="Indicator" name=""/>
    <alias index="5" field="Sub_Indic" name=""/>
    <alias index="6" field="Area_Type" name=""/>
    <alias index="7" field="Activity" name=""/>
    <alias index="8" field="Source" name=""/>
  </aliases>
  <defaults>
    <default expression="" field="GEF_CP_ID" applyOnUpdate="0"/>
    <default expression="" field="Country" applyOnUpdate="0"/>
    <default expression="" field="Site_ID" applyOnUpdate="0"/>
    <default expression="" field="Date" applyOnUpdate="0"/>
    <default expression="" field="Indicator" applyOnUpdate="0"/>
    <default expression="" field="Sub_Indic" applyOnUpdate="0"/>
    <default expression="" field="Area_Type" applyOnUpdate="0"/>
    <default expression="" field="Activity" applyOnUpdate="0"/>
    <default expression="" field="Source" applyOnUpdate="0"/>
  </defaults>
  <constraints>
    <constraint unique_strength="0" notnull_strength="1" constraints="1" field="GEF_CP_ID" exp_strength="0"/>
    <constraint unique_strength="0" notnull_strength="1" constraints="1" field="Country" exp_strength="0"/>
    <constraint unique_strength="1" notnull_strength="1" constraints="3" field="Site_ID" exp_strength="0"/>
    <constraint unique_strength="0" notnull_strength="1" constraints="1" field="Date" exp_strength="0"/>
    <constraint unique_strength="0" notnull_strength="1" constraints="1" field="Indicator" exp_strength="0"/>
    <constraint unique_strength="0" notnull_strength="1" constraints="1" field="Sub_Indic" exp_strength="0"/>
    <constraint unique_strength="0" notnull_strength="0" constraints="0" field="Area_Type" exp_strength="0"/>
    <constraint unique_strength="0" notnull_strength="0" constraints="0" field="Activity" exp_strength="0"/>
    <constraint unique_strength="0" notnull_strength="0" constraints="0" field="Source" exp_strength="0"/>
  </constraints>
  <constraintExpressions>
    <constraint desc="" field="GEF_CP_ID" exp=""/>
    <constraint desc="" field="Country" exp=""/>
    <constraint desc="" field="Site_ID" exp=""/>
    <constraint desc="" field="Date" exp=""/>
    <constraint desc="" field="Indicator" exp=""/>
    <constraint desc="" field="Sub_Indic" exp=""/>
    <constraint desc="" field="Area_Type" exp=""/>
    <constraint desc="" field="Activity" exp=""/>
    <constraint desc="" field="Source" exp=""/>
  </constraintExpressions>
  <expressionfields/>
  <editform tolerant="1"></editform>
  <editforminit/>
  <editforminitcodesource>0</editforminitcodesource>
  <editforminitfilepath></editforminitfilepath>
  <editforminitcode><![CDATA[]]></editforminitcode>
  <featformsuppress>0</featformsuppress>
  <editorlayout>generatedlayout</editorlayout>
  <editable/>
  <labelOnTop/>
  <reuseLastValue/>
  <dataDefinedFieldProperties/>
  <widgets/>
  <layerGeometryType>2</layerGeometryType>
</qgis>
