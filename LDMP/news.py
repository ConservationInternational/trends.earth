"""
/***************************************************************************
 LDMP - A QGIS plugin
 This plugin supports monitoring and reporting of land degradation to the UNCCD
 and in support of the SDG Land Degradation Neutrality (LDN) target.
                              -------------------
        begin                : 2026-03-14
        git sha              : $Format:%H$
        copyright            : (C) 2026 by Conservation International
        email                : trends.earth@conservation.org
 ***************************************************************************/

News module for displaying announcements and updates to users.
"""

import json
import typing
from dataclasses import dataclass
from datetime import datetime

from qgis.core import QgsSettings
from qgis.PyQt import QtCore

from ._version import __version__
from .api import APIClient
from .constants import get_api_url
from .logger import log

# Settings keys for news management
SETTINGS_DISMISSED_NEWS = "trends_earth/news/dismissed_ids"
SETTINGS_LAST_NEWS_FETCH = "trends_earth/news/last_fetch_timestamp"
SETTINGS_CACHED_NEWS = "trends_earth/news/cached_items"
SETTINGS_CACHED_NEWS_LANG = "trends_earth/news/cached_lang"

# Minimum interval between news fetches (24 hours in seconds)
MIN_FETCH_INTERVAL = 24 * 60 * 60


def substitute_url_placeholders(url: str) -> str:
    """
    Substitute placeholders in a URL with actual values.

    Supported placeholders:
        {token} - The user's JWT access token (refreshed if needed)
        {lang} - The user's current QGIS language (e.g., "en", "fr", "es")

    The access token is automatically refreshed if expired or about to expire.

    Args:
        url: URL string potentially containing placeholders

    Returns:
        URL with placeholders replaced by actual values
    """
    # Handle {lang} placeholder
    if "{lang}" in url:
        from qgis.core import QgsApplication

        locale = QgsApplication.locale()
        # Extract just the language code (e.g., "en" from "en_US")
        lang = locale.split("_")[0] if locale else "en"
        url = url.replace("{lang}", lang)

    if "{token}" in url:
        from .api import APIClient
        from .auth import get_jwt_tokens
        from .constants import get_api_url

        access_token, refresh_token = get_jwt_tokens()

        if "{token}" in url:
            if access_token:
                # Check if token is expired and refresh if needed
                api_client = APIClient(url=get_api_url())
                if api_client._is_token_expired(access_token):
                    log("Access token expired or expiring soon, refreshing...")
                    new_token = api_client._refresh_access_token(refresh_token)
                    if new_token:
                        access_token = new_token
                        log("Token refreshed successfully for URL substitution")
                    else:
                        log("Warning: Failed to refresh expired token")
                        # Remove the token parameter to avoid using an invalid token
                        url = (
                            url.replace("token={token}&", "")
                            .replace("&token={token}", "")
                            .replace("?token={token}", "")
                        )
                        access_token = None

                if access_token:
                    url = url.replace("{token}", access_token)
            else:
                log("Warning: {token} placeholder in URL but user is not logged in")
                # Remove the token parameter to avoid broken URLs
                url = (
                    url.replace("token={token}&", "")
                    .replace("&token={token}", "")
                    .replace("?token={token}", "")
                )

        if "{refresh_token}" in url:
            if refresh_token:
                url = url.replace("{refresh_token}", refresh_token)
            else:
                url = (
                    url.replace("refresh_token={refresh_token}&", "")
                    .replace("&refresh_token={refresh_token}", "")
                    .replace("?refresh_token={refresh_token}", "")
                )

    return url


def open_news_link(url: str) -> None:
    """
    Open a news link URL, substituting any placeholders first.

    This function handles {token} and other placeholders in URLs,
    allowing news items to include links that require authentication.

    Args:
        url: The URL to open, potentially containing placeholders
    """
    from qgis.PyQt.QtCore import QUrl
    from qgis.PyQt.QtGui import QDesktopServices

    final_url = substitute_url_placeholders(url)
    log(f"Opening news link: {final_url[:50]}...")
    QDesktopServices.openUrl(QUrl(final_url))


@dataclass
class NewsItem:
    """Data class representing a news item from the API."""

    id: str
    title: str
    message: str
    message_html: typing.Optional[str] = None
    link_url: typing.Optional[str] = None
    link_text: typing.Optional[str] = None
    news_type: str = "announcement"
    priority: int = 0
    publish_at: typing.Optional[str] = None
    expires_at: typing.Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "NewsItem":
        """Create a NewsItem from API response dict."""
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            message=data.get("message", ""),
            message_html=data.get("message_html"),
            link_url=data.get("link_url"),
            link_text=data.get("link_text", "Learn more"),
            news_type=data.get("news_type", "announcement"),
            priority=data.get("priority", 0),
            publish_at=data.get("publish_at"),
            expires_at=data.get("expires_at"),
        )

    def to_dict(self) -> dict:
        """Convert NewsItem to a dict for caching."""
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "message_html": self.message_html,
            "link_url": self.link_url,
            "link_text": self.link_text,
            "news_type": self.news_type,
            "priority": self.priority,
            "publish_at": self.publish_at,
            "expires_at": self.expires_at,
        }


class NewsClient(QtCore.QObject):
    """Client for fetching news items from the API."""

    news_fetched = QtCore.pyqtSignal(list)  # Emits list of NewsItem
    fetch_error = QtCore.pyqtSignal(str)  # Emits error message

    def __init__(self, parent=None):
        super().__init__(parent)
        self.api_client = APIClient(url=get_api_url(), timeout=15)

    def should_fetch_news(self, force: bool = False) -> bool:
        """
        Check if enough time has passed since the last fetch.

        Args:
            force: If True, always return True (for manual refresh)

        Returns:
            True if news should be fetched, False otherwise
        """
        if force:
            return True

        settings = QgsSettings()
        last_fetch = settings.value(SETTINGS_LAST_NEWS_FETCH, 0, type=int)
        current_time = int(datetime.now().timestamp())

        return (current_time - last_fetch) >= MIN_FETCH_INTERVAL

    def _update_last_fetch_timestamp(self) -> None:
        """Update the last fetch timestamp in settings."""
        settings = QgsSettings()
        current_time = int(datetime.now().timestamp())
        settings.setValue(SETTINGS_LAST_NEWS_FETCH, current_time)

    def _get_current_lang(self) -> str:
        """Get the current QGIS language code."""
        from qgis.core import QgsApplication

        locale = QgsApplication.locale()
        return locale.split("_")[0] if locale else "en"

    def _cache_news_items(self, news_items: typing.List["NewsItem"], lang: str) -> None:
        """Cache news items and the language they were fetched in."""
        settings = QgsSettings()
        items_data = [item.to_dict() for item in news_items]
        settings.setValue(SETTINGS_CACHED_NEWS, json.dumps(items_data))
        settings.setValue(SETTINGS_CACHED_NEWS_LANG, lang)

    def _load_cached_news(self) -> typing.List["NewsItem"]:
        """Load cached news items from settings."""
        settings = QgsSettings()
        cached_json = settings.value(SETTINGS_CACHED_NEWS, "[]")
        try:
            items_data = json.loads(cached_json)
            return [NewsItem.from_dict(item) for item in items_data]
        except (json.JSONDecodeError, Exception) as e:
            log(f"Error loading cached news: {e}")
            return []

    def fetch_news(self, platform: str = "qgis_plugin", force: bool = False) -> None:
        """
        Fetch news items from the API.

        Args:
            platform: The platform to filter news for (qgis_plugin, web, api_ui)
            force: If True, fetch regardless of last fetch time
        """
        lang = self._get_current_lang()

        # Invalidate cache when the language has changed
        settings = QgsSettings()
        cached_lang = settings.value(SETTINGS_CACHED_NEWS_LANG, "")
        lang_changed = cached_lang != lang

        # Check if we should fetch (throttle to once per day unless forced)
        if not lang_changed and not self.should_fetch_news(force):
            cached_items = self._load_cached_news()
            # If cache is empty, force a fetch
            if not cached_items:
                log("Cache empty - forcing news fetch")
            else:
                log(
                    f"Skipping news fetch - loaded {len(cached_items)} cached news items"
                )
                self.news_fetched.emit(cached_items)
                return

        if lang_changed:
            log(f"Language changed from '{cached_lang}' to '{lang}' - refreshing news")

        try:
            endpoint = (
                f"/api/v1/news?platform={platform}&version={__version__}&lang={lang}"
            )

            log(f"Fetching news from {endpoint}")
            response = self.api_client.call_api(endpoint, method="get", use_token=False)

            if response is not None:
                news_data = response.get("data", [])
                news_items = [NewsItem.from_dict(item) for item in news_data]
                log(f"Fetched {len(news_items)} news items")
                self._update_last_fetch_timestamp()
                self._cache_news_items(news_items, lang)
                self.news_fetched.emit(news_items)
            else:
                log("No response from news API")
                self.news_fetched.emit([])

        except Exception as e:
            error_msg = f"Error fetching news: {e}"
            log(error_msg)
            self.fetch_error.emit(error_msg)
            self.news_fetched.emit([])

    def dismiss_news(self, news_id: str) -> bool:
        """
        Dismiss a news item.

        Args:
            news_id: The ID of the news item to dismiss

        Returns:
            True if successful
        """
        _add_dismissed_news_id(news_id)
        log(f"Dismissed news item {news_id} locally")
        return True


def _get_dismissed_news_ids() -> typing.Set[str]:
    """Get the set of dismissed news IDs from local settings."""
    settings = QgsSettings()
    dismissed_json = settings.value(SETTINGS_DISMISSED_NEWS, "[]")
    try:
        dismissed_list = json.loads(dismissed_json)
        return set(dismissed_list)
    except json.JSONDecodeError:
        return set()


def _add_dismissed_news_id(news_id: str) -> None:
    """Add a news ID to the dismissed set in local settings."""
    dismissed = _get_dismissed_news_ids()
    dismissed.add(news_id)
    settings = QgsSettings()
    settings.setValue(SETTINGS_DISMISSED_NEWS, json.dumps(list(dismissed)))


def _is_news_dismissed(news_id: str) -> bool:
    """Check if a news item has been dismissed locally."""
    return news_id in _get_dismissed_news_ids()
