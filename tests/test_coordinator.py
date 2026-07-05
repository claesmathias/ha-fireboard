"""Tests for FireBoard data update coordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.fireboard.coordinator import FireBoardDataUpdateCoordinator


async def test_coordinator_update_success(
    hass, mock_config_entry_data, mock_device_data, mock_temperature_data
):
    """Test successful coordinator update.

    Patches FireBoardMQTTClient (as imported into coordinator.py's own
    namespace) so async_refresh()'s first-run _async_setup() doesn't open a
    real network connection to fireboard.io.
    """
    config_entry = ConfigEntry(
        domain="fireboard",
        title="Test",
        data=mock_config_entry_data,
    )

    with (
        patch(
            "custom_components.fireboard.coordinator.FireBoardApiClient"
        ) as mock_client_class,
        patch(
            "custom_components.fireboard.coordinator.FireBoardMQTTClient"
        ) as mock_mqtt_class,
    ):
        mock_client = AsyncMock()
        mock_client._token = "test-token"
        mock_client.auth_token = "test-token"
        mock_client.session_cookies = {"sessionid": "test-session"}
        mock_client.authenticate = AsyncMock(return_value=True)
        mock_client.get_devices = AsyncMock(return_value=[mock_device_data])
        mock_client_class.return_value = mock_client
        # FireBoardMQTTClient's own methods (connect, subscribe_device, ...) are
        # synchronous and run via hass.async_add_executor_job, so use MagicMock
        # rather than AsyncMock to match their real (non-coroutine) call signature.
        mock_mqtt_class.return_value = MagicMock()

        coordinator = FireBoardDataUpdateCoordinator(hass, config_entry)

        # Manually set the client to our mock
        coordinator.client = mock_client

        await coordinator.async_refresh()

        assert coordinator.last_update_success
        assert mock_device_data["uuid"] in coordinator.data
        assert coordinator.data[mock_device_data["uuid"]]["online"] is True


async def test_coordinator_authentication(hass, mock_config_entry_data):
    """Test _async_update_data re-authenticates when no token is cached yet.

    Calls _async_update_data() directly rather than async_refresh(), since
    _async_setup() (invoked by the base class on first refresh) would also
    unconditionally authenticate and mask what this test is checking.
    """
    config_entry = ConfigEntry(
        domain="fireboard",
        title="Test",
        data=mock_config_entry_data,
    )

    with patch(
        "custom_components.fireboard.coordinator.FireBoardApiClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_client.auth_token = None  # No token cached yet
        mock_client.authenticate = AsyncMock(return_value=True)
        mock_client.get_devices = AsyncMock(return_value=[])
        mock_client_class.return_value = mock_client

        coordinator = FireBoardDataUpdateCoordinator(hass, config_entry)
        coordinator.client = mock_client

        await coordinator._async_update_data()

        # Verify authenticate was called since auth_token was missing
        mock_client.authenticate.assert_called_once()


async def test_coordinator_rate_limit_error(hass, mock_config_entry_data):
    """Test coordinator surfaces rate limit errors from _async_update_data.

    Note: real HA's DataUpdateCoordinator.async_refresh() catches UpdateFailed
    and turns it into last_update_success=False rather than propagating it, so
    this exercises our own _async_update_data() override directly rather than
    the base class's refresh cycle.
    """
    from homeassistant.config_entries import ConfigEntry

    from custom_components.fireboard.api_client import FireBoardApiClientRateLimitError

    config_entry = ConfigEntry(
        version=1,
        domain="fireboard",
        title="Test",
        data=mock_config_entry_data,
        source="user",
    )

    with patch(
        "custom_components.fireboard.coordinator.FireBoardApiClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_client._token = "test-token"
        mock_client.auth_token = "test-token"
        mock_client.get_devices = AsyncMock(
            side_effect=FireBoardApiClientRateLimitError("Rate limited")
        )
        mock_client_class.return_value = mock_client

        coordinator = FireBoardDataUpdateCoordinator(hass, config_entry)
        coordinator.client = mock_client

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()


async def test_coordinator_communication_error(hass, mock_config_entry_data):
    """Test coordinator surfaces communication errors from _async_update_data."""
    from homeassistant.config_entries import ConfigEntry

    from custom_components.fireboard.api_client import (
        FireBoardApiClientCommunicationError,
    )

    config_entry = ConfigEntry(
        version=1,
        domain="fireboard",
        title="Test",
        data=mock_config_entry_data,
        source="user",
    )

    with patch(
        "custom_components.fireboard.coordinator.FireBoardApiClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_client._token = "test-token"
        mock_client.auth_token = "test-token"
        mock_client.get_devices = AsyncMock(
            side_effect=FireBoardApiClientCommunicationError("Connection error")
        )
        mock_client_class.return_value = mock_client

        coordinator = FireBoardDataUpdateCoordinator(hass, config_entry)
        coordinator.client = mock_client

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()


async def test_coordinator_preserves_mqtt_temperatures_across_refresh(
    hass, mock_config_entry_data, mock_device_data, mock_temperature_data
):
    """Test that a REST refresh keeps temperature data pushed earlier via MQTT.

    coordinator.py's _async_update_data explicitly carries forward the
    "temperatures" dict already in self.data so an MQTT-pushed reading isn't
    wiped out by the next periodic REST device-list refresh.
    """
    config_entry = ConfigEntry(
        domain="fireboard",
        title="Test",
        data=mock_config_entry_data,
    )

    with patch(
        "custom_components.fireboard.coordinator.FireBoardApiClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_client._token = "test-token"
        mock_client.auth_token = "test-token"
        mock_client.get_devices = AsyncMock(return_value=[mock_device_data])
        mock_client_class.return_value = mock_client

        coordinator = FireBoardDataUpdateCoordinator(hass, config_entry)
        coordinator.client = mock_client
        coordinator.data = {
            mock_device_data["uuid"]: {"temperatures": mock_temperature_data}
        }

        result = await coordinator._async_update_data()

        assert result[mock_device_data["uuid"]]["online"] is True
        assert result[mock_device_data["uuid"]]["temperatures"] == mock_temperature_data


async def test_async_setup_connects_mqtt_when_credentials_available(
    hass, mock_config_entry_data
):
    """Test _async_setup connects MQTT when credentials are available.

    Authenticates and connects the MQTT client when the API client has both
    an auth token and session cookies available.
    """
    config_entry = ConfigEntry(
        domain="fireboard", title="Test", data=mock_config_entry_data
    )

    with (
        patch(
            "custom_components.fireboard.coordinator.FireBoardApiClient"
        ) as mock_client_class,
        patch(
            "custom_components.fireboard.coordinator.FireBoardMQTTClient"
        ) as mock_mqtt_class,
    ):
        mock_client = AsyncMock()
        mock_client.authenticate = AsyncMock(return_value=True)
        mock_client.auth_token = "test-token"
        mock_client.session_cookies = {"sessionid": "test-session"}
        mock_client_class.return_value = mock_client

        mock_mqtt_instance = MagicMock()
        mock_mqtt_class.return_value = mock_mqtt_instance

        coordinator = FireBoardDataUpdateCoordinator(hass, config_entry)
        coordinator.client = mock_client

        await coordinator._async_setup()

        mock_client.authenticate.assert_called_once()
        mock_mqtt_class.assert_called_once_with(
            auth_token="test-token",
            session_cookies={"sessionid": "test-session"},
            on_message_callback=coordinator._handle_mqtt_message,
        )
        mock_mqtt_instance.connect.assert_called_once()
        assert coordinator.mqtt_client is mock_mqtt_instance


async def test_async_setup_skips_mqtt_without_credentials(hass, mock_config_entry_data):
    """Test _async_setup leaves mqtt_client unset without credentials.

    There's no auth token or session cookies to connect with in this case.
    """
    config_entry = ConfigEntry(
        domain="fireboard", title="Test", data=mock_config_entry_data
    )

    with patch(
        "custom_components.fireboard.coordinator.FireBoardApiClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_client.authenticate = AsyncMock(return_value=True)
        mock_client.auth_token = None
        mock_client.session_cookies = {}
        mock_client_class.return_value = mock_client

        coordinator = FireBoardDataUpdateCoordinator(hass, config_entry)
        coordinator.client = mock_client

        await coordinator._async_setup()

        assert coordinator.mqtt_client is None


async def test_async_setup_falls_back_to_polling_on_error(hass, mock_config_entry_data):
    """Test _async_setup swallows setup errors instead of failing outright.

    E.g. an auth failure shouldn't fail coordinator setup entirely, since
    REST polling can still work.
    """
    config_entry = ConfigEntry(
        domain="fireboard", title="Test", data=mock_config_entry_data
    )

    with patch(
        "custom_components.fireboard.coordinator.FireBoardApiClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_client.authenticate = AsyncMock(side_effect=RuntimeError("network down"))
        mock_client_class.return_value = mock_client

        coordinator = FireBoardDataUpdateCoordinator(hass, config_entry)
        coordinator.client = mock_client
        coordinator.mqtt_client = "sentinel-should-be-cleared"

        await coordinator._async_setup()  # must not raise

        assert coordinator.mqtt_client is None


async def test_handle_mqtt_message_updates_existing_channel(
    hass, mock_config_entry_data, mock_device_data, mock_temperature_data
):
    """Test an MQTT push for a known channel updates that channel in place."""
    config_entry = ConfigEntry(
        domain="fireboard", title="Test", data=mock_config_entry_data
    )
    coordinator = FireBoardDataUpdateCoordinator(hass, config_entry)
    coordinator.data = {
        mock_device_data["uuid"]: {
            "temperatures": mock_temperature_data,
            "online": False,
        }
    }

    coordinator._handle_mqtt_message(
        mock_device_data["uuid"],
        {"channel": 1, "temp": 300.0, "p": True, "date": "2024-01-01T00:00:00Z"},
    )

    channels = coordinator.data[mock_device_data["uuid"]]["temperatures"]["channels"]
    channel_1 = next(ch for ch in channels if ch["channel"] == 1)
    assert channel_1["current_temp"] == 300.0
    assert channel_1["probe_present"] is True
    assert coordinator.data[mock_device_data["uuid"]]["online"] is True


async def test_handle_mqtt_message_adds_new_channel(
    hass, mock_config_entry_data, mock_device_data
):
    """Test an MQTT push for a device with no temperature data yet creates it."""
    config_entry = ConfigEntry(
        domain="fireboard", title="Test", data=mock_config_entry_data
    )
    coordinator = FireBoardDataUpdateCoordinator(hass, config_entry)
    coordinator.data = {mock_device_data["uuid"]: {}}

    coordinator._handle_mqtt_message(
        mock_device_data["uuid"],
        {"channel": 5, "temp": 120.0, "p": False, "date": "2024-01-01T00:00:00Z"},
    )

    channels = coordinator.data[mock_device_data["uuid"]]["temperatures"]["channels"]
    assert len(channels) == 1
    assert channels[0]["channel"] == 5
    assert channels[0]["current_temp"] == 120.0
    assert channels[0]["probe_present"] is False


async def test_handle_mqtt_message_ignores_unknown_device(hass, mock_config_entry_data):
    """Test an MQTT push for a device not tracked by the coordinator is a no-op."""
    config_entry = ConfigEntry(
        domain="fireboard", title="Test", data=mock_config_entry_data
    )
    coordinator = FireBoardDataUpdateCoordinator(hass, config_entry)
    coordinator.data = {"some-other-device": {}}

    # Must not raise even though "unknown-device" isn't in coordinator.data
    coordinator._handle_mqtt_message("unknown-device", {"channel": 1, "temp": 100.0})

    assert "unknown-device" not in coordinator.data


async def test_async_update_data_wraps_unexpected_errors(hass, mock_config_entry_data):
    """Test an unexpected error from get_devices is still wrapped in UpdateFailed.

    A raw, non-FireBoard exception must not propagate as-is.
    """
    config_entry = ConfigEntry(
        domain="fireboard", title="Test", data=mock_config_entry_data
    )

    with patch(
        "custom_components.fireboard.coordinator.FireBoardApiClient"
    ) as mock_client_class:
        mock_client = AsyncMock()
        mock_client.auth_token = "test-token"
        mock_client.get_devices = AsyncMock(side_effect=RuntimeError("boom"))
        mock_client_class.return_value = mock_client

        coordinator = FireBoardDataUpdateCoordinator(hass, config_entry)
        coordinator.client = mock_client

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()


async def test_async_shutdown_disconnects_mqtt_client(hass, mock_config_entry_data):
    """Test async_shutdown disconnects an active MQTT client via the executor."""
    config_entry = ConfigEntry(
        domain="fireboard", title="Test", data=mock_config_entry_data
    )
    coordinator = FireBoardDataUpdateCoordinator(hass, config_entry)
    coordinator.mqtt_client = MagicMock()

    await coordinator.async_shutdown()

    coordinator.mqtt_client.disconnect.assert_called_once()


async def test_async_shutdown_without_mqtt_client(hass, mock_config_entry_data):
    """Test async_shutdown is a no-op when MQTT was never connected."""
    config_entry = ConfigEntry(
        domain="fireboard", title="Test", data=mock_config_entry_data
    )
    coordinator = FireBoardDataUpdateCoordinator(hass, config_entry)
    coordinator.mqtt_client = None

    await coordinator.async_shutdown()  # must not raise


async def test_first_refresh_failure_raises_config_entry_not_ready(
    hass, mock_config_entry_data
):
    """Test a failed first update surfaces as ConfigEntryNotReady.

    This is what tells Home Assistant to retry integration setup later
    instead of treating the config entry as permanently broken.
    """
    config_entry = ConfigEntry(
        domain="fireboard", title="Test", data=mock_config_entry_data
    )

    with (
        patch(
            "custom_components.fireboard.coordinator.FireBoardApiClient"
        ) as mock_client_class,
        patch(
            "custom_components.fireboard.coordinator.FireBoardMQTTClient"
        ) as mock_mqtt_class,
    ):
        mock_client = AsyncMock()
        mock_client.authenticate = AsyncMock(return_value=True)
        mock_client.auth_token = "test-token"
        mock_client.session_cookies = {"sessionid": "test-session"}
        mock_client.get_devices = AsyncMock(side_effect=RuntimeError("boom"))
        mock_client_class.return_value = mock_client
        mock_mqtt_class.return_value = MagicMock()

        coordinator = FireBoardDataUpdateCoordinator(hass, config_entry)
        coordinator.client = mock_client

        with pytest.raises(ConfigEntryNotReady):
            await coordinator.async_config_entry_first_refresh()
