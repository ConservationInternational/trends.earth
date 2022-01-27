<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:xs="http://www.w3.org/2001/XMLSchema"
    xmlns:gml="http://www.opengis.net/gml" xmlns:gmd="http://www.isotc211.org/2005/gmd"
                xmlns:gco="http://www.isotc211.org/2005/gco"
    exclude-result-prefixes="xs"
    version="1.0">
    
    
    <xsl:template match="/">
      <gmd:MD_Metadata xmlns:gml="http://www.opengis.net/gml" xmlns:gmd="http://www.isotc211.org/2005/gmd"
                       xmlns:gco="http://www.isotc211.org/2005/gco">
            
            <!-- Identifier -->
            <gmd:fileIdentifier>
                <gco:CharacterString><xsl:value-of select="qgis/identifier"/></gco:CharacterString>
            </gmd:fileIdentifier>

            <!-- Fixed value for the time being. TODO: Retrieve from QGIS metadata, but values are 2 code chars or freetext in GQGIS -->
            <gmd:language>
                <gmd:LanguageCode codeList="http://www.loc.gov/standards/iso639-2/" codeListValue="eng"/>
            </gmd:language>
            
            <gmd:characterSet>
                <gmd:MD_CharacterSetCode codeListValue="utf8"
                    codeList="http://standards.iso.org/ittf/PubliclyAvailableStandards/ISO_19139_Schemas/resources/codelist/ML_gmxCodelists.xml#MD_CharacterSetCode"/>
            </gmd:characterSet>
            
            <!-- Parent identifier -->
            <xsl:if test="string(qgis/parentidentifier)">
            <gmd:parentIdentifier>
                <gco:CharacterString><xsl:value-of select="qgis/parentidentifier"/></gco:CharacterString>
            </gmd:parentIdentifier>
           </xsl:if>
            
            <!-- Hierarchy level -->
            <xsl:if test="string(qgis/type)">
            <gmd:hierarchyLevel>
                <gmd:MD_ScopeCode
                    codeList="http://www.isotc211.org/2005/resources/Codelist/gmxCodelists.xml#MD_ScopeCode"
                    codeListValue="{qgis/type}"/>
            </gmd:hierarchyLevel>
            </xsl:if>
            
            <!-- Metadata contact -->
            <xsl:call-template name="contact">
                <xsl:with-param name="contact" select="qgis/contact" />
                <xsl:with-param name="element" select="'gmd:contact'" />
            </xsl:call-template>
          
            <!-- In XSLT 1.0 we can't deal with date functions, will be updated by GeoNetwork -->
            <gmd:dateStamp>
                <gco:DateTime>2019-08-20T08:49:27</gco:DateTime>
            </gmd:dateStamp>
            
            <gmd:metadataStandardName>
                <gco:CharacterString>ISO 19115:2003/19139</gco:CharacterString>
            </gmd:metadataStandardName>
            
            <gmd:metadataStandardVersion>
                <gco:CharacterString>1.0</gco:CharacterString>
            </gmd:metadataStandardVersion>
            
          
            <!-- Reference system info -->
            <xsl:if test="string(qgis/crs/spatialrefsys/authid)">
            <gmd:referenceSystemInfo>
                <gmd:MD_ReferenceSystem>
                    <gmd:referenceSystemIdentifier>
                       <gmd:RS_Identifier>
                           <gmd:code>
                               <gco:CharacterString><xsl:value-of select="qgis/crs/spatialrefsys/authid"/></gco:CharacterString>
                           </gmd:code>
                       </gmd:RS_Identifier>
                    </gmd:referenceSystemIdentifier>
                </gmd:MD_ReferenceSystem>
            </gmd:referenceSystemInfo>
            </xsl:if>
            
            <gmd:identificationInfo>
                <gmd:MD_DataIdentification>
                    <gmd:citation>
                        <gmd:CI_Citation>
                            <!-- Title -->
                            <gmd:title>
                                <gco:CharacterString><xsl:value-of select="qgis/title"/></gco:CharacterString>
                            </gmd:title>
                        
                            <!-- TODO: Check dates, not available in QGIS metadata -->
                            <gmd:date>
                                <gmd:CI_Date>
                                    <gmd:date>
                                        <gco:Date/>
                                    </gmd:date>
                                    <gmd:dateType>
                                        <gmd:CI_DateTypeCode codeListValue="publication"
                                            codeList="http://www.isotc211.org/2005/resources/codeList.xml#CI_DateTypeCode"/>
                                    </gmd:dateType>
                                </gmd:CI_Date>
                            </gmd:date>
                        </gmd:CI_Citation>
                    </gmd:citation>
                    
                    <!-- Abstract -->
                    <gmd:abstract>
                        <gco:CharacterString><xsl:value-of select="qgis/abstract"/></gco:CharacterString>
                    </gmd:abstract>
                    
                   <!-- Metadata dataset contact -->
                   <xsl:call-template name="contact">
                       <xsl:with-param name="contact" select="qgis/contact" />
                       <xsl:with-param name="element" select="'gmd:pointOfContact'" />
                   </xsl:call-template>
      
                    <!-- Free text keywords -->
                    <xsl:if test="qgis/keywords[@vocabulary='']">
                    <gmd:descriptiveKeywords>
                        <gmd:MD_Keywords>
                            <xsl:for-each select="qgis/keywords[@vocabulary='']/keyword">
                                <gmd:keyword>
                                    <gco:CharacterString><xsl:value-of select="."/></gco:CharacterString>
                                </gmd:keyword>
                            </xsl:for-each>
                            <gmd:type>
                                <gmd:MD_KeywordTypeCode codeListValue="theme"
                                    codeList="http://standards.iso.org/ittf/PubliclyAvailableStandards/ISO_19139_Schemas/resources/codelist/ML_gmxCodelists.xml#MD_KeywordTypeCode"/>
                            </gmd:type>                           
                        </gmd:MD_Keywords>
                    </gmd:descriptiveKeywords>
                    </xsl:if>
                  
                    <!-- Vocabulary keywords --> 
                    <xsl:if test="qgis/keywords[@vocabulary!='' and @vocabulary!='gmd:topicCategory']">
                        <xsl:for-each select="qgis/keywords[@vocabulary!='' and @vocabulary!='gmd:topicCategory']">
                            <gmd:descriptiveKeywords>
                                <gmd:MD_Keywords>
                                    <xsl:for-each select="keyword">
                                        <gmd:keyword>
                                            <gco:CharacterString><xsl:value-of select="."/></gco:CharacterString>
                                        </gmd:keyword>
                                    </xsl:for-each>
                                    <gmd:type>
                                        <gmd:MD_KeywordTypeCode codeListValue="theme"
                                            codeList="http://standards.iso.org/ittf/PubliclyAvailableStandards/ISO_19139_Schemas/resources/codelist/ML_gmxCodelists.xml#MD_KeywordTypeCode"/>
                                    </gmd:type>      
                                    <gmd:thesaurusName>
                                        <gmd:CI_Citation>
                                            <gmd:title>
                                                <gco:CharacterString><xsl:value-of select="@vocabulary"/></gco:CharacterString>
                                            </gmd:title>
                                            
                                            <!-- TODO: Check dates, not available in QGIS metadata -->
                                            <gmd:date>
                                                <gmd:CI_Date>
                                                    <gmd:date>
                                                        <gco:Date/>
                                                    </gmd:date>
                                                    <gmd:dateType>
                                                        <gmd:CI_DateTypeCode codeListValue="publication"
                                                            codeList="http://www.isotc211.org/2005/resources/codeList.xml#CI_DateTypeCode"/>
                                                    </gmd:dateType>
                                                </gmd:CI_Date>
                                            </gmd:date>
                                        </gmd:CI_Citation>
                                    </gmd:thesaurusName>
                                </gmd:MD_Keywords>
                            </gmd:descriptiveKeywords>
                        </xsl:for-each>
                      
                    </xsl:if>              
                     
                    <!-- Fees/License and constraints -->
                    <xsl:if test="string(qgis/fees)">
                    <gmd:resourceConstraints>
                        <gmd:MD_Constraints>
                            <gmd:useLimitation>
                                <gco:CharacterString><xsl:value-of select="qgis/fees"/></gco:CharacterString>
                            </gmd:useLimitation>
                        </gmd:MD_Constraints>
                    </gmd:resourceConstraints>
                    </xsl:if>
                    
                    <xsl:if test="string(qgis/license)">
                    <gmd:resourceConstraints>
                        <gmd:MD_LegalConstraints>
                            <gmd:accessConstraints>
                                <gmd:MD_RestrictionCode
                                    codeList="http://www.isotc211.org/2005/resources/Codelist/gmxCodelists.xml#MD_RestrictionCode"
                                    codeListValue="otherRestrictions" />
                            </gmd:accessConstraints>                        
                            <gmd:otherConstraints>
                                <gco:CharacterString><xsl:value-of select="qgis/license"/></gco:CharacterString>
                            </gmd:otherConstraints>
                        </gmd:MD_LegalConstraints>
                    </gmd:resourceConstraints>
                    </xsl:if>
                    
                    <!-- Use constraints -->
                    <xsl:if test="qgis/constraints[@type='use'] or qgis/constraints[@type='access'] or qgis/constraints[@type='other']">
                    <gmd:resourceConstraints>
                        <gmd:MD_LegalConstraints>
                            <!-- Use constraints -->
                            <xsl:for-each select="qgis/constraints[@type='use']">
                            <gmd:useConstraints>
                                <gmd:MD_RestrictionCode
                                    codeList="http://www.isotc211.org/2005/resources/Codelist/gmxCodelists.xml#MD_RestrictionCode"
                                    codeListValue="{.}" />
                            </gmd:useConstraints>    
                            </xsl:for-each>
                            
                            <!-- Access constraints -->
                            <xsl:for-each select="qgis/constraints[@type='access']">
                                <gmd:accessConstraints>
                                    <gmd:MD_RestrictionCode
                                        codeList="http://www.isotc211.org/2005/resources/Codelist/gmxCodelists.xml#MD_RestrictionCode"
                                        codeListValue="{.}" />
                                </gmd:accessConstraints>          
                            </xsl:for-each>

                            <!-- Other constraints -->
                            <xsl:for-each select="qgis/constraints[@type='other']">
                                <gmd:otherConstraints>
                                    <gco:CharacterString><xsl:value-of select="."/></gco:CharacterString>
                                </gmd:otherConstraints>            
                            </xsl:for-each>
                        </gmd:MD_LegalConstraints>
                    </gmd:resourceConstraints>
                    </xsl:if>
                
                    <!-- Fixed value for the time being. TODO: Retrieve from QGIS metadata, but values are 2 code chars or freetext in GQGIS -->                   
                    <gmd:language>
                        <gmd:LanguageCode codeList="http://www.loc.gov/standards/iso639-2/" codeListValue="eng"/>
                    </gmd:language>
                    
                    <gmd:characterSet>
                        <gmd:MD_CharacterSetCode codeListValue="utf8"
                                             codeList="http://standards.iso.org/ittf/PubliclyAvailableStandards/ISO_19139_Schemas/resources/codelist/ML_gmxCodelists.xml#MD_CharacterSetCode"/>
                    </gmd:characterSet>

                    <!-- Topic categories -->
                    <xsl:variable name="lowercase" select="'abcdefghijklmnopqrstuvwxyz'" />
                    <xsl:variable name="uppercase" select="'ABCDEFGHIJKLMNOPQRSTUVWXYZ'" />
                    
                    
                    <xsl:for-each select="qgis/keywords[@vocabulary='gmd:topicCategory']/keyword">
                    <gmd:topicCategory>
                        <gmd:MD_TopicCategoryCode><xsl:value-of select="translate(., $uppercase, $lowercase)" /></gmd:MD_TopicCategoryCode>
                    </gmd:topicCategory>
                    </xsl:for-each>
                 
                    <!-- Temporal extent -->
                    <xsl:if test="string(qgis/extent/temporal/period/start) or string(qgis/extent/temporal/period/end)">
                        <gmd:extent>
                            <gmd:EX_Extent>
                                <gmd:temporalElement>
                                    <gmd:EX_TemporalExtent>
                                        <gmd:extent>
                                            <gml:TimePeriod gml:id="d6780e395a1050910">
                                                <gml:beginPosition><xsl:value-of select="qgis/extent/temporal/period/start"/></gml:beginPosition>
                                                <gml:endPosition><xsl:value-of select="qgis/extent/temporal/period/end"/></gml:endPosition>
                                            </gml:TimePeriod>
                                        </gmd:extent>
                                    </gmd:EX_TemporalExtent>
                                </gmd:temporalElement>
                            </gmd:EX_Extent>
                        </gmd:extent>
                    </xsl:if>
                     
                    <xsl:choose>
                        <!-- There's a spatial extent in 4326? -->
                        <xsl:when test="qgis/extent/spatial[@crs='EPSG:4326']">
                            <gmd:extent>
                                <gmd:EX_Extent>
                                    <gmd:geographicElement>
                                        <gmd:EX_GeographicBoundingBox>
                                            <gmd:westBoundLongitude>
                                                <gco:Decimal><xsl:value-of select="qgis/extent/spatial[@crs='EPSG:4326']/@minx" /></gco:Decimal>
                                            </gmd:westBoundLongitude>
                                            <gmd:eastBoundLongitude>
                                                <gco:Decimal><xsl:value-of select="qgis/extent/spatial[@crs='EPSG:4326']/@maxx" /></gco:Decimal>
                                            </gmd:eastBoundLongitude>
                                            <gmd:southBoundLatitude>
                                                <gco:Decimal><xsl:value-of select="qgis/extent/spatial[@crs='EPSG:4326']/@miny" /></gco:Decimal>
                                            </gmd:southBoundLatitude>
                                            <gmd:northBoundLatitude>
                                                <gco:Decimal><xsl:value-of select="qgis/extent/spatial[@crs='EPSG:4326']/@maxy" /></gco:Decimal>
                                            </gmd:northBoundLatitude>
                                        </gmd:EX_GeographicBoundingBox>
                                    </gmd:geographicElement>
                                </gmd:EX_Extent>
                            </gmd:extent>
                        </xsl:when>
                        
                        <!-- Default bbox extent -->
                        <xsl:otherwise>
                            <gmd:extent>
                                <gmd:EX_Extent>
                                    <gmd:geographicElement>
                                        <gmd:EX_GeographicBoundingBox>
                                            <gmd:westBoundLongitude>
                                                <gco:Decimal>-180</gco:Decimal>
                                            </gmd:westBoundLongitude>
                                            <gmd:eastBoundLongitude>
                                                <gco:Decimal>180</gco:Decimal>
                                            </gmd:eastBoundLongitude>
                                            <gmd:southBoundLatitude>
                                                <gco:Decimal>-90</gco:Decimal>
                                            </gmd:southBoundLatitude>
                                            <gmd:northBoundLatitude>
                                                <gco:Decimal>90</gco:Decimal>
                                            </gmd:northBoundLatitude>
                                        </gmd:EX_GeographicBoundingBox>
                                    </gmd:geographicElement>
                                </gmd:EX_Extent>
                            </gmd:extent>
                        </xsl:otherwise>
                    </xsl:choose>
                 
             
              </gmd:MD_DataIdentification>
           </gmd:identificationInfo>
             
             <!-- Online resources and formats -->
             
            <gmd:distributionInfo>
                <gmd:MD_Distribution>
                    <xsl:if test="count(qgis/links/link[@format!='']) > 0">
                        
                        <xsl:for-each select="qgis/links/link[string(@format)]">
                            <!-- TODO: Deal with duplicated values, in XSLT 1.0 no functions available for this -->
                            <gmd:distributionFormat>
                                <gmd:MD_Format>
                                    <gmd:name>
                                        <gco:CharacterString><xsl:value-of select="@format"/></gco:CharacterString>
                                    </gmd:name>    
                                    <gmd:version>
                                        <gco:CharacterString></gco:CharacterString>
                                    </gmd:version>
                                </gmd:MD_Format>
                            </gmd:distributionFormat>      
                        </xsl:for-each>
                        
                    </xsl:if>
                    
                    <!-- Distributor contact -->
                    <gmd:distributor>
                        <gmd:MD_Distributor>
                            <xsl:call-template name="contact">
                                <xsl:with-param name="contact" select="qgis/contact" />
                                <xsl:with-param name="element" select="'gmd:distributorContact'" />
                            </xsl:call-template>
                        </gmd:MD_Distributor>
                    </gmd:distributor>
                    
                    <gmd:transferOptions>
                        <gmd:MD_DigitalTransferOptions>
                            <xsl:for-each select="qgis/links/link">
                                <gmd:onLine>
                                    <gmd:CI_OnlineResource>
                                        <gmd:linkage>
                                            <gmd:URL><xsl:value-of select="@url"/></gmd:URL>
                                        </gmd:linkage>
                                        <gmd:protocol>
                                            <gco:CharacterString>
                                                <xsl:choose>
                                                    <!-- GeoNetwork special value -->
                                                    <xsl:when test="@type='WWW:LINK'">WWW:LINK-1.0-http--link</xsl:when>
                                                    <xsl:otherwise><xsl:value-of select="@type" /></xsl:otherwise>
                                                </xsl:choose>
                                                </gco:CharacterString>
                                        </gmd:protocol>
                                        <gmd:name>
                                            <gco:CharacterString><xsl:value-of select="@name"/></gco:CharacterString>
                                        </gmd:name>
                                        <gmd:description>
                                            <gco:CharacterString><xsl:value-of select="@description"/></gco:CharacterString>
                                        </gmd:description>     
                                    </gmd:CI_OnlineResource>
                                </gmd:onLine>
                            </xsl:for-each>
                        </gmd:MD_DigitalTransferOptions>
                    </gmd:transferOptions>
                </gmd:MD_Distribution>
            </gmd:distributionInfo>
            
           
        </gmd:MD_Metadata>
        
    </xsl:template>
    
    
    <xsl:template name="contact">
        <xsl:param name="contact" />
        <xsl:param name="element" />
        
        <xsl:element name="{$element}" namespace="http://www.isotc211.org/2005/gmd">
            <gmd:CI_ResponsibleParty>
                <gmd:individualName >
                    <gco:CharacterString><xsl:value-of select="$contact/name"/></gco:CharacterString>
                </gmd:individualName>
                <gmd:organisationName>
                    <gco:CharacterString><xsl:value-of select="$contact/organization"/></gco:CharacterString>
                </gmd:organisationName>
                <gmd:positionName>
                    <gco:CharacterString><xsl:value-of select="$contact/position"/></gco:CharacterString>
                </gmd:positionName>
                <gmd:contactInfo>
                    <gmd:CI_Contact>
                        <gmd:phone>
                            <gmd:CI_Telephone>
                                <gmd:voice>
                                    <gco:CharacterString><xsl:value-of select="$contact/voice"/></gco:CharacterString>
                                </gmd:voice>
                                <gmd:facsimile>
                                    <gco:CharacterString><xsl:value-of select="$contact/fax"/></gco:CharacterString>
                                </gmd:facsimile>
                            </gmd:CI_Telephone>
                        </gmd:phone>
                        
                        <!-- Process addresses of type Postal -->
                        <xsl:for-each select="$contact/contactAddress[type='postal']">
                            <gmd:address>
                                <gmd:CI_Address>
                                    <gmd:deliveryPoint>
                                        <gco:CharacterString><xsl:value-of select="address"/></gco:CharacterString>
                                    </gmd:deliveryPoint>
                                    <gmd:city>
                                        <gco:CharacterString><xsl:value-of select="city"/></gco:CharacterString>
                                    </gmd:city>
                                    <gmd:administrativeArea>
                                        <gco:CharacterString><xsl:value-of select="administrativearea"/></gco:CharacterString>
                                    </gmd:administrativeArea>
                                    <gmd:postalCode>
                                        <gco:CharacterString><xsl:value-of select="postalcode"/></gco:CharacterString>
                                    </gmd:postalCode>
                                    <gmd:country>
                                        <gco:CharacterString><xsl:value-of select="country"/></gco:CharacterString>
                                    </gmd:country>
                                    <gmd:electronicMailAddress>
                                        <gco:CharacterString><xsl:value-of select="$contact/email"/></gco:CharacterString>
                                    </gmd:electronicMailAddress>
                                </gmd:CI_Address>
                            </gmd:address>
                        </xsl:for-each>
                    
                    </gmd:CI_Contact>
                </gmd:contactInfo>
                <gmd:role>
                    <gmd:CI_RoleCode codeListValue="{$contact/role}"
                        codeList="http://standards.iso.org/ittf/PubliclyAvailableStandards/ISO_19139_Schemas/resources/codelist/ML_gmxCodelists.xml#CI_RoleCode"/>
                </gmd:role>
            </gmd:CI_ResponsibleParty>
        </xsl:element>
    </xsl:template>
</xsl:stylesheet>