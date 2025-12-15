"""
Test JWT refresh token functionality for the Trends.Earth API client
"""

import base64
import json
import sys
import time
from unittest.mock import Mock, patch

import pytest

# Mock QGIS dependencies
sys_modules = [
    "qgis",
    "qgis.core",
    "qgis.PyQt",
    "qgis.PyQt.QtCore",
    "qgis.PyQt.QtNetwork",
]

for module in sys_modules:
    if module not in sys.modules:
        sys.modules[module] = Mock()

from LDMP.api import APIClient  # noqa: E402


class TestJWTRefresh:
    def create_jwt_token(self, exp_time=None):
        """Create a mock JWT token with expiration time"""
        if exp_time is None:
            exp_time = int(time.time()) + 3600  # 1 hour from now

        header = {"alg": "HS256", "typ": "JWT"}
        payload = {"sub": "user123", "iat": int(time.time()), "exp": exp_time}

        # Create JWT-like token (header.payload.signature)
        header_b64 = (
            base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
        )
        payload_b64 = (
            base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        )
        signature = "fake_signature"

        return f"{header_b64}.{payload_b64}.{signature}"

    def test_decode_jwt_payload(self):
        """Test JWT payload decoding"""
        client = APIClient("https://api.trends.earth")

        # Create a test token
        token = self.create_jwt_token()

        # Decode payload
        payload = client._decode_jwt_payload(token)

        assert payload is not None
        assert "exp" in payload
        assert "sub" in payload
        assert payload["sub"] == "user123"

    def test_is_token_expired(self):
        """Test token expiration checking"""
        client = APIClient("https://api.trends.earth")

        # Test with expired token
        expired_token = self.create_jwt_token(exp_time=int(time.time()) - 100)
        assert client._is_token_expired(expired_token)

        # Test with valid token (expires in 1 hour)
        valid_token = self.create_jwt_token(exp_time=int(time.time()) + 3600)
        assert not client._is_token_expired(valid_token)

        # Test with token expiring soon (within buffer)
        soon_expired_token = self.create_jwt_token(
            exp_time=int(time.time()) + 100
        )  # 100 seconds
        assert client._is_token_expired(soon_expired_token, buffer_seconds=300)

    @patch("LDMP.api.QgsSettings")
    def test_store_and_get_tokens(self, mock_settings):
        """Test token storage and retrieval"""
        client = APIClient("https://api.trends.earth")

        # Mock settings instance
        mock_settings_instance = Mock()
        mock_settings.return_value = mock_settings_instance

        # Test storing tokens
        access_token = "access_token_123"
        refresh_token = "refresh_token_456"

        client._store_tokens(access_token, refresh_token)

        # Verify tokens were stored
        mock_settings_instance.setValue.assert_any_call(
            "trendsearth/access_token", access_token
        )
        mock_settings_instance.setValue.assert_any_call(
            "trendsearth/refresh_token", refresh_token
        )

        # Mock retrieval
        mock_settings_instance.value.side_effect = lambda key, default=None: {
            "trendsearth/access_token": access_token,
            "trendsearth/refresh_token": refresh_token,
        }.get(key, default)

        # Test getting tokens
        stored_access, stored_refresh = client._get_stored_tokens()

        assert stored_access == access_token
        assert stored_refresh == refresh_token

    @patch("LDMP.api.QgsSettings")
    def test_clear_stored_tokens(self, mock_settings):
        """Test clearing stored tokens"""
        client = APIClient("https://api.trends.earth")

        # Mock settings instance
        mock_settings_instance = Mock()
        mock_settings.return_value = mock_settings_instance

        client._clear_stored_tokens()

        # Verify tokens were cleared
        mock_settings_instance.setValue.assert_any_call(
            "trendsearth/access_token", None
        )
        mock_settings_instance.setValue.assert_any_call(
            "trendsearth/refresh_token", None
        )

    @patch("LDMP.api.QgsSettings")
    def test_refresh_access_token(self, mock_settings):
        """Test access token refresh"""
        client = APIClient("https://api.trends.earth")

        # Mock the call_api method
        with patch.object(client, "call_api") as mock_call_api:
            mock_call_api.return_value = {
                "access_token": "new_access_token",
                "refresh_token": "new_refresh_token",
            }

            # Mock settings instance
            mock_settings_instance = Mock()
            mock_settings.return_value = mock_settings_instance

            # Test refresh
            result = client._refresh_access_token("old_refresh_token")

            # Verify call was made correctly
            mock_call_api.assert_called_once_with(
                "/auth/refresh",
                method="post",
                payload={"refresh_token": "old_refresh_token"},
                use_token=False,
            )

            # Verify new token was returned
            assert result == "new_access_token"

            # Verify tokens were stored
            mock_settings_instance.setValue.assert_any_call(
                "trendsearth/access_token", "new_access_token"
            )
            mock_settings_instance.setValue.assert_any_call(
                "trendsearth/refresh_token", "new_refresh_token"
            )

    @patch("LDMP.api.QgsSettings")
    @patch("LDMP.api.auth")
    def test_login_with_stored_valid_token(self, mock_auth, mock_settings):
        """Test login using valid stored token"""
        client = APIClient("https://api.trends.earth")

        # Create valid token
        valid_token = self.create_jwt_token()

        # Mock settings instance
        mock_settings_instance = Mock()
        mock_settings.return_value = mock_settings_instance
        mock_settings_instance.value.side_effect = lambda key, default=None: {
            "trendsearth/access_token": valid_token,
            "trendsearth/refresh_token": "refresh_token_123",
        }.get(key, default)

        # Mock conf.settings_manager
        with patch("LDMP.api.conf") as mock_conf:
            mock_conf.settings_manager.get_value.return_value = True

            result = client.login()

            # Should return stored token without API call
            assert result == valid_token

    @patch("LDMP.api.QgsSettings")
    @patch("LDMP.api.auth")
    def test_login_with_expired_token_refresh_success(self, mock_auth, mock_settings):
        """Test login with expired token that successfully refreshes"""
        client = APIClient("https://api.trends.earth")

        # Create expired token
        expired_token = self.create_jwt_token(exp_time=int(time.time()) - 100)

        # Mock settings instance
        mock_settings_instance = Mock()
        mock_settings.return_value = mock_settings_instance
        mock_settings_instance.value.side_effect = lambda key, default=None: {
            "trendsearth/access_token": expired_token,
            "trendsearth/refresh_token": "refresh_token_123",
        }.get(key, default)

        # Mock the refresh token call
        with patch.object(client, "_refresh_access_token") as mock_refresh:
            mock_refresh.return_value = "new_access_token"

            with patch("LDMP.api.conf") as mock_conf:
                mock_conf.settings_manager.get_value.return_value = True

                result = client.login()

                # Should have attempted refresh
                mock_refresh.assert_called_once_with("refresh_token_123")

                # Should return new token
                assert result == "new_access_token"

    @patch("LDMP.api.QgsSettings")
    @patch("LDMP.api.auth")
    def test_login_fresh_when_refresh_fails(self, mock_auth, mock_settings):
        """Test fresh login when token refresh fails"""
        client = APIClient("https://api.trends.earth")

        # Create expired token
        expired_token = self.create_jwt_token(exp_time=int(time.time()) - 100)

        # Mock settings instance
        mock_settings_instance = Mock()
        mock_settings.return_value = mock_settings_instance
        mock_settings_instance.value.side_effect = lambda key, default=None: {
            "trendsearth/access_token": expired_token,
            "trendsearth/refresh_token": "refresh_token_123",
        }.get(key, default)

        # Mock auth config
        mock_auth_config = Mock()
        mock_auth_config.config.side_effect = lambda key: {
            "username": "test@example.com",
            "password": "testpass",
        }.get(key)
        mock_auth.get_auth_config.return_value = mock_auth_config

        # Mock failed refresh but successful fresh login
        with patch.object(client, "_refresh_access_token") as mock_refresh:
            mock_refresh.return_value = None  # Refresh fails

            with patch.object(client, "call_api") as mock_call_api:
                mock_call_api.return_value = {
                    "access_token": "fresh_access_token",
                    "refresh_token": "fresh_refresh_token",
                }

                with patch("LDMP.api.conf") as mock_conf:
                    mock_conf.settings_manager.get_value.return_value = True

                    result = client.login()

                    # Should have attempted refresh first
                    mock_refresh.assert_called_once_with("refresh_token_123")

                    # Should have made fresh login call
                    mock_call_api.assert_called_once_with(
                        "/auth",
                        method="post",
                        payload={"email": "test@example.com", "password": "testpass"},
                        use_token=False,
                    )

                    # Should return fresh token
                    assert result == "fresh_access_token"


if __name__ == "__main__":
    pytest.main([__file__])
