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

from qgis.core import QgsApplication, QgsAuthMethodConfig
from qgis.PyQt import QtCore

from .logger import log


def _push_critical(title: str, msg: str):
    """
    Thread‑safe wrapper around iface.messageBar().pushCritical.
    """
    log(message=msg)
    # iface.messageBar().pushMessage(title, msg, level=Qgis.Critical, duration=3)


class tr_auth(QtCore.QObject):
    def tr(message):
        return QtCore.QCoreApplication.translate("tr_auth", message)


@dataclasses.dataclass()
class AuthSetup:
    name: str

    @property
    def key(self):
        return f"{self.name}_authId"


TE_API_AUTH_SETUP = AuthSetup(name="Trends.Earth")

LANDPKS_AUTH_SETUP = AuthSetup(name="LandPKS")

# Auth config for JWT token storage (encrypted via QGIS Auth Manager)
_TOKEN_AUTH_CONFIG_NAME = "Trends.Earth JWT Tokens"
_TOKEN_AUTH_CONFIG_SETTINGS_KEY = "trendsearth/token_auth_id"


def store_jwt_tokens(access_token=None, refresh_token=None):
    """Store JWT tokens using QGIS Auth Manager for encrypted storage.

    Tokens are stored in a dedicated auth config entry, with the access_token
    in the 'username' field and the refresh_token in the 'password' field.
    """
    auth_mgr = QgsApplication.authManager()
    config_id = QtCore.QSettings().value(_TOKEN_AUTH_CONFIG_SETTINGS_KEY, None)

    auth_config = QgsAuthMethodConfig()
    existing = False

    if config_id:
        ok = auth_mgr.loadAuthenticationConfig(config_id, auth_config, True)
        if ok and auth_config.isValid():
            existing = True

    if not existing:
        auth_config = QgsAuthMethodConfig()
        auth_config.setName(_TOKEN_AUTH_CONFIG_NAME)

    auth_config.setMethod("Basic")
    if access_token is not None:
        auth_config.setConfig("username", access_token)
    if refresh_token is not None:
        auth_config.setConfig("password", refresh_token)

    if existing:
        auth_mgr.updateAuthenticationConfig(auth_config)
    else:
        auth_mgr.storeAuthenticationConfig(auth_config)
        QtCore.QSettings().setValue(_TOKEN_AUTH_CONFIG_SETTINGS_KEY, auth_config.id())

    log("JWT tokens stored securely via auth manager")


def get_jwt_tokens():
    """Retrieve JWT tokens from QGIS Auth Manager.

    Returns:
        Tuple of (access_token, refresh_token), either may be None.
    """
    config_id = QtCore.QSettings().value(_TOKEN_AUTH_CONFIG_SETTINGS_KEY, None)
    if not config_id:
        return None, None

    auth_config = QgsAuthMethodConfig()
    ok = QgsApplication.authManager().loadAuthenticationConfig(
        config_id, auth_config, True
    )

    if not ok or not auth_config.isValid():
        return None, None

    access_token = auth_config.config("username") or None
    refresh_token = auth_config.config("password") or None
    return access_token, refresh_token


def clear_jwt_tokens():
    """Clear JWT tokens from QGIS Auth Manager."""
    config_id = QtCore.QSettings().value(_TOKEN_AUTH_CONFIG_SETTINGS_KEY, None)

    if config_id:
        QgsApplication.authManager().removeAuthenticationConfig(config_id)
        QtCore.QSettings().remove(_TOKEN_AUTH_CONFIG_SETTINGS_KEY)

    # Also clear any legacy plaintext tokens from QgsSettings
    from qgis.core import QgsSettings

    settings = QgsSettings()
    settings.remove("trendsearth/access_token")
    settings.remove("trendsearth/refresh_token")

    log("Stored JWT tokens cleared")


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
    currentAuthConfig.setMethod("Basic")
    currentAuthConfig.setConfig("username", email)
    currentAuthConfig.setConfig("password", password)

    if not previousAuthExist:
        # store a new auth config
        if not QgsApplication.authManager().storeAuthenticationConfig(
            currentAuthConfig
        ):
            _push_critical("Trends.Earth", tr_auth.tr("Cannot init auth configuration"))
            return None
    else:
        # update existing
        if not QgsApplication.authManager().updateAuthenticationConfig(
            currentAuthConfig
        ):
            _push_critical(
                "Trends.Earth", tr_auth.tr("Cannot update auth configuration")
            )
            return None

    QtCore.QSettings().setValue(
        f"trends_earth/{auth_setup.key}", currentAuthConfig.id()
    )
    return currentAuthConfig.id()


def remove_current_auth_config(auth_setup):
    authConfigId = QtCore.QSettings().value(f"trends_earth/{auth_setup.key}", None)
    if not authConfigId:
        _push_critical(
            "Trends.Earth",
            tr_auth.tr(
                f"No authentication set for {auth_setup.name}. "
                "Setup in Trends.Earth settings"
            ),
        )
        return None
    log(f"remove_current_auth_config for {auth_setup.name} with ID {authConfigId}")

    if not QgsApplication.authManager().removeAuthenticationConfig(authConfigId):
        _push_critical(
            "Trends.Earth",
            tr_auth.tr(
                f"Cannot remove auth configuration for "
                f"{auth_setup.name} with id: {authConfigId}"
            ),
        )
        return False

    QtCore.QSettings().setValue(f"trends_earth/{auth_setup.key}", None)

    # Also clear any stored JWT tokens when removing auth config
    if auth_setup == TE_API_AUTH_SETUP:
        clear_jwt_tokens()

    return True


def get_auth_config(auth_setup, authConfigId=None, warn=True):
    def _warn(msg: str):
        """Push a critical message only if 'warn' is True, thread-safe."""
        if warn:
            _push_critical("Trends.Earth", msg)

    if not authConfigId:
        # not set then retrieve from config if set
        authConfigId = QtCore.QSettings().value(f"trends_earth/{auth_setup.key}", None)
        if not authConfigId:
            _warn(
                tr_auth.tr(
                    "No authentication set. "
                    f"Setup username and password before using {auth_setup.name}."
                )
            )
            return None
    log(f"get_auth_config for {auth_setup.name} with auth id {authConfigId}")

    configs = QgsApplication.authManager().availableAuthMethodConfigs()
    # message_bar = iface.messageBar()
    if authConfigId not in configs:
        _warn(
            tr_auth.tr(
                f"Cannot retrieve credentials with id {authConfigId}. "
                "Setup username and password before using "
                f"{auth_setup.name} functions."
            )
        )
        return None

    authConfig = QgsAuthMethodConfig()
    ok = QgsApplication.authManager().loadAuthenticationConfig(
        authConfigId, authConfig, True
    )
    if not ok or not authConfig.isValid():
        _warn(
            tr_auth.tr(
                f"{auth_setup.name} credentials with id {authConfigId} "
                "are not valid.  Setup username and password before using "
                f"{auth_setup.name}."
            )
        )
        return None

    # check if auth method is the only supported for no
    if authConfig.method() != "Basic":
        _warn(
            tr_auth.tr(
                f"Auth method with id {authConfigId} is '{authConfig.method()}'. "
                f"This method is not supported by {auth_setup.name}."
            )
        )
        return None

    return authConfig
