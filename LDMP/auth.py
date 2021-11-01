# -*- coding: utf-8 -*-
"""
/***************************************************************************
 LDMP - A QGIS plugin
 This plugin supports monitoring and reporting of land degradation to the UNCCD
 and in support of the SDG Land Degradation Neutrality (LDN) target.
                              -------------------
        begin                : 2017-05-23
        git sha              : $Format:%H$
        copyright            : (C) 2017 by Conservation International
        email                : trends.earth@conservation.org
 ***************************************************************************/
"""

import dataclasses

from qgis.PyQt import (
    QtCore,
)

from qgis.utils import iface
from qgis.core import (
    QgsAuthMethodConfig,
    QgsApplication
)

from .logger import log


@dataclasses.dataclass()
class AuthSetup:
    name: str

    @property
    def key(self):
        return f'{self.name}_authId'


TE_API_AUTH_SETUP = AuthSetup(
    name='Trends.Earth'
)

LANDPKS_AUTH_SETUP = AuthSetup(
    name='LandPKS'
)


def tr(message):
    return QtCore.QCoreApplication.translate("tr_auth", message)


def init_auth_config(
    auth_setup,
    email=None,
    password=None,
):
    currentAuthConfig = None

    # check if an auth method for this service was already set
    configs = QgsApplication.authManager().availableAuthMethodConfigs()
    previousAuthExist = False
    for config in configs.values():
        if config.name() == auth_setup.name:
            currentAuthConfig = config
            previousAuthExist = True
            break

    if not previousAuthExist:
        # not found => create a new one
        currentAuthConfig = QgsAuthMethodConfig()
        currentAuthConfig.setName(auth_setup.name)

    # reset it's config values to set later new password when received
    currentAuthConfig.setMethod('Basic')
    currentAuthConfig.setConfig('username', email)
    currentAuthConfig.setConfig('password', password)

    if not previousAuthExist:
        # store a new auth config
        if not QgsApplication.authManager().storeAuthenticationConfig(currentAuthConfig):
            iface.messageBar().pushCritical(
                'Trends.Earth',
                tr('Cannot init auth configuration')
            )
            return None
    else:
        # update existing
         if not QgsApplication.authManager().updateAuthenticationConfig(currentAuthConfig):
            iface.messageBar().pushCritical(
                'Trends.Earth',
                tr('Cannot update auth configuration')
            )
            return None

    QtCore.QSettings().setValue(f"trends_earth/{auth_setup.key}",
                                currentAuthConfig.id())
    return currentAuthConfig.id()

def remove_current_auth_config(auth_setup):
    authConfigId = QtCore.QSettings().value(f"trends_earth/{auth_setup.key}", None)
    if not authConfigId:
        iface.messageBar().pushCritical(
            'Trends.Earth',
            tr(f'No authentication set for {auth_setup.name}. '
               'Setup in Trends.Earth settings')
        )
        return None
    log(f'remove_current_auth_config for {auth_setup.name} with ID {authConfigId}')

    if not QgsApplication.authManager().removeAuthenticationConfig(authConfigId):
        iface.messageBar().pushCritical(
            'Trends.Earth',
            tr(
                f'Cannot remove auth configuration for '
                f'{auth_setup.name} with id: {authConfigId}'
            )
        )
        return False

    QtCore.QSettings().setValue("trends_earth/{auth_setup.key}", None)
    return True

def get_auth_config(
    auth_setup,
    authConfigId=None,
    warn=True
):
    if not authConfigId:
        # not set then retrieve from config if set
        authConfigId = QtCore.QSettings().value(f"trends_earth/{auth_setup.key}", None)
        if not authConfigId:
            if warn:
                iface.messageBar().pushCritical(
                    'Trends.Earth',
                    tr(
                        'No authentication set. Setup username and password '
                        f'before using {auth_setup.name} functions.'
                    )
                )
            return None
    log(f'get_auth_config for {auth_setup.name} with auth id {authConfigId}')

    configs = QgsApplication.authManager().availableAuthMethodConfigs()
    message_bar = iface.messageBar()
    if authConfigId not in configs.keys():
        if warn:
            message_bar.pushCritical(
                'Trends.Earth',
                tr(
                    f'Cannot retrieve credentials with id {authConfigId}. '
                    'Setup username and password before using '
                    f'{auth_setup.name} functions.'
                )
            )

        return None

    authConfig = QgsAuthMethodConfig()
    ok = QgsApplication.authManager().loadAuthenticationConfig(authConfigId, authConfig, True)
    if not ok:
        if warn:
            message_bar.pushCritical(
                'Trends.Earth',
                tr(
                    f'Cannot retrieve {auth_setup.name} credentials with id '
                    f'{authConfigId}. Setup username and password before '
                    f'using {auth_setup.name} functions.'
                )
            )
        return None

    if not authConfig.isValid():
        if warn:
            message_bar.pushCritical(
                'Trends.Earth',
                tr(
                    f'{auth_setup.name} credentials with id {authConfigId} '
                    'are not valid. Setup username and password before using '
                    f'{auth_setup.name}.'
                )
            )
        return None

    # check if auth method is the only supported for no
    if authConfig.method() != 'Basic':
        if warn:
            message_bar.pushCritical(
                'Trends.Earth',
                tr(
                    f'Auth method with id {authConfigId} is '
                    f'{authConfig.method()}. This method is not supported by '
                    f'by {auth_setup.name}'
                )
            )
        return None

    return authConfig
