# API related constants
DEFAULT_API_URL = "https://api.trends.earth"
# Deprecated: Use get_api_url() instead for configurable API URL support
API_URL = DEFAULT_API_URL
TIMEOUT = 30


def get_api_url() -> str:
    """Get the configured API URL.

    Returns the custom API URL from settings if configured,
    otherwise returns the default API URL (https://api.trends.earth).

    Returns:
        str: The API URL to use for all API requests.
    """
    try:
        from . import conf

        # Check if settings_manager is available (may not be during initial import)
        if hasattr(conf, "settings_manager"):
            custom_url = conf.settings_manager.get_value(conf.Setting.CUSTOM_API_URL)
            if custom_url and custom_url.strip():
                return custom_url.strip().rstrip("/")
    except (ImportError, AttributeError):
        # During initial module loading, conf may not be fully initialized
        pass
    return DEFAULT_API_URL
