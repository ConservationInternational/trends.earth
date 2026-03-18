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
from pathlib import Path

from qgis.core import QgsSettings
from qgis.PyQt import QtCore, QtWidgets, uic

from ._version import __version__
from .api import APIClient
from .constants import get_api_url
from .logger import log

# Load the UI
WidgetNewsUi, _ = uic.loadUiType(str(Path(__file__).parent / "gui/WidgetNews.ui"))

# Settings keys for news management
SETTINGS_DISMISSED_NEWS = "trends_earth/news/dismissed_ids"
SETTINGS_LAST_NEWS_FETCH = "trends_earth/news/last_fetch_timestamp"
SETTINGS_CACHED_NEWS = "trends_earth/news/cached_items"

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

    def _cache_news_items(self, news_items: typing.List["NewsItem"]) -> None:
        """Cache news items in settings for later retrieval."""
        settings = QgsSettings()
        # Convert to list of dicts for JSON serialization
        items_data = [item.to_dict() for item in news_items]
        settings.setValue(SETTINGS_CACHED_NEWS, json.dumps(items_data))

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
        # Check if we should fetch (throttle to once per day unless forced)
        if not self.should_fetch_news(force):
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

        try:
            # Get user's language for translated news content
            from qgis.core import QgsApplication

            locale = QgsApplication.locale()
            # Extract just the language code (e.g., "en" from "en_US")
            lang = locale.split("_")[0] if locale else "en"

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
                self._cache_news_items(news_items)
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


class NewsWidget(QtWidgets.QWidget, WidgetNewsUi):
    """Widget for displaying news items in the plugin."""

    dismissed = QtCore.pyqtSignal(str)  # Emits news ID when dismissed
    refresh_requested = QtCore.pyqtSignal()  # Emits when refresh is requested

    # Color schemes for different news types
    NEWS_STYLES = {
        "info": {
            "background": "#e3f2fd",
            "border": "#2196f3",
            "icon": "ℹ️",
        },
        "warning": {
            "background": "#fff3e0",
            "border": "#ff9800",
            "icon": "⚠️",
        },
        "alert": {
            "background": "#ffebee",
            "border": "#f44336",
            "icon": "🚨",
        },
        "update": {
            "background": "#e8f5e9",
            "border": "#4caf50",
            "icon": "🆕",
        },
        "success": {
            "background": "#e8f5e9",
            "border": "#4caf50",
            "icon": "✅",
        },
        "error": {
            "background": "#ffebee",
            "border": "#f44336",
            "icon": "❌",
        },
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self._news_items: typing.List[NewsItem] = []
        self._current_index: int = 0
        self._news_client = NewsClient(self)

        # Connect signals
        self.dismiss_button.clicked.connect(self._on_dismiss)
        self.prev_button.clicked.connect(self._show_previous)
        self.next_button.clicked.connect(self._show_next)
        self._news_client.news_fetched.connect(self._on_news_fetched)

        # Connect refresh button if it exists
        if hasattr(self, "refresh_button"):
            self.refresh_button.clicked.connect(self._on_refresh)

        # Enable rich text in message label and handle links with placeholder support
        self.news_message_label.setTextFormat(QtCore.Qt.RichText)
        self.news_message_label.setOpenExternalLinks(False)
        self.news_message_label.linkActivated.connect(open_news_link)
        self.news_message_label.setWordWrap(True)

        # Enable links in link label with placeholder support
        self.news_link_label.setTextFormat(QtCore.Qt.RichText)
        self.news_link_label.setOpenExternalLinks(False)
        self.news_link_label.linkActivated.connect(open_news_link)

        # Initially hidden until news is loaded
        self.hide()

    def refresh_news(self, force: bool = False) -> None:
        """
        Fetch and display fresh news items.

        Args:
            force: If True, fetch regardless of last fetch time
        """
        self._news_client.fetch_news(platform="qgis_plugin", force=force)

    def _on_refresh(self) -> None:
        """Handle refresh button click."""
        self.refresh_news(force=True)
        self.refresh_requested.emit()

    def _on_news_fetched(self, news_items: typing.List[NewsItem]) -> None:
        """Handle fetched news items."""
        # Filter out locally dismissed items
        self._news_items = [
            item for item in news_items if not _is_news_dismissed(item.id)
        ]

        if self._news_items:
            self._current_index = 0
            self._update_display()
            self.show()
        else:
            self.hide()

    def _update_display(self) -> None:
        """Update the widget display with the current news item."""
        if not self._news_items:
            self.hide()
            return

        item = self._news_items[self._current_index]

        # Update title and message
        self.news_title_label.setText(item.title)
        # Use pre-rendered HTML from API - ensure rich text format is set
        log(f"News display: message_html exists={item.message_html is not None}")
        if item.message_html:
            log(f"message_html content: {item.message_html[:100]}...")
        self.news_message_label.setTextFormat(QtCore.Qt.RichText)
        self.news_message_label.setText(item.message_html if item.message_html else "")

        # Update link
        if item.link_url:
            link_text = item.link_text or "Learn more"
            self.news_link_label.setText(f'<a href="{item.link_url}">{link_text}</a>')
            self.news_link_label.show()
        else:
            self.news_link_label.hide()

        # Update counter
        total = len(self._news_items)
        self.news_counter_label.setText(f"{self._current_index + 1} / {total}")

        # Update navigation buttons
        self.prev_button.setEnabled(self._current_index > 0)
        self.next_button.setEnabled(self._current_index < total - 1)

        # Hide navigation if only one item
        show_nav = total > 1
        self.prev_button.setVisible(show_nav)
        self.next_button.setVisible(show_nav)
        self.news_counter_label.setVisible(show_nav)

        # Apply style based on news type
        style = self.NEWS_STYLES.get(item.news_type, self.NEWS_STYLES["info"])
        self.news_icon_label.setText(style["icon"])
        self.news_frame.setStyleSheet(
            f"""
            QFrame#news_frame {{
                background-color: {style["background"]};
                border: 1px solid {style["border"]};
                border-radius: 4px;
            }}
            """
        )

    def _on_dismiss(self) -> None:
        """Handle dismiss button click."""
        if not self._news_items:
            return

        item = self._news_items[self._current_index]
        news_id = item.id

        # Dismiss on server/locally
        self._news_client.dismiss_news(news_id)

        # Remove from current list
        self._news_items.pop(self._current_index)

        # Emit signal
        self.dismissed.emit(news_id)

        # Update display
        if self._news_items:
            # Adjust index if needed
            if self._current_index >= len(self._news_items):
                self._current_index = len(self._news_items) - 1
            self._update_display()
        else:
            self.hide()

    def _show_previous(self) -> None:
        """Show the previous news item."""
        if self._current_index > 0:
            self._current_index -= 1
            self._update_display()

    def _show_next(self) -> None:
        """Show the next news item."""
        if self._current_index < len(self._news_items) - 1:
            self._current_index += 1
            self._update_display()

    def set_news_items(self, items: typing.List[NewsItem]) -> None:
        """
        Set news items directly (for testing or manual updates).

        Args:
            items: List of NewsItem objects to display
        """
        self._news_items = [item for item in items if not _is_news_dismissed(item.id)]

        if self._news_items:
            self._current_index = 0
            self._update_display()
            self.show()
        else:
            self.hide()

    def has_news(self) -> bool:
        """Check if there are any news items to display."""
        return len(self._news_items) > 0
