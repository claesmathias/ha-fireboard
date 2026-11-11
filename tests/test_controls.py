"""Tests for FireBoard Drive control (number/button) and the API commands."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError

from custom_components.fireboard.api_client import (
    FireBoardApiClient,
    FireBoardApiClientCommunicationError,
)
from custom_components.fireboard.const import CONF_DRIVE_CONTROLS, DOMAIN
from custom_components.fireboard.coordinator import FireBoardDataUpdateCoordinator

UUID = "test-device-uuid-123"


@pytest.fixture
def drive_data(mock_coordinator_data):
    """Coordinator data for a device with a Drive attached."""
    mock_coordinator_data[UUID]["device_info"]["last_drivelog"] = {
        "setpoint": 225.0,
        "driveper": 0.42,
        "modetype": 2,
        "degreetype": 2,
        "tiedchannel": 1,
    }
    return mock_coordinator_data


@pytest.fixture
def coordinator(hass, drive_data, mock_config_entry_data):
    """Return a real coordinator with a mocked API client."""
    entry = ConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    coord = FireBoardDataUpdateCoordinator(hass, entry)
    coord.client = AsyncMock()
    coord.data = drive_data
    return coord


def _drive_buttons(entities):
    from custom_components.fireboard.button import FireBoardDriveOffButton

    return [e for e in entities if isinstance(e, FireBoardDriveOffButton)]


async def _setup(hass, platform, coordinator, options=None):
    entry = ConfigEntry(domain=DOMAIN, options=options or {})
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entities = []
    await platform.async_setup_entry(hass, entry, entities.extend)
    return entities


async def test_number_entities_created_for_drive(hass, coordinator):
    """Setpoint and fan speed controls exist for Drive devices."""
    from custom_components.fireboard import number

    entities = await _setup(hass, number, coordinator)
    names = sorted(e.name for e in entities)
    assert names == [
        "Test FireBoard Drive Manual Fan Speed",
        "Test FireBoard Drive Target Temperature",
    ]


async def test_controls_disabled_by_option(hass, coordinator):
    """The drive_controls option removes all control entities."""
    from custom_components.fireboard import button, number

    opts = {CONF_DRIVE_CONTROLS: False}
    assert await _setup(hass, number, coordinator, opts) == []
    assert _drive_buttons(await _setup(hass, button, coordinator, opts)) == []


async def test_no_controls_without_drive(hass, coordinator):
    """Devices without a drivelog get no controls."""
    from custom_components.fireboard import button, number

    coordinator.data[UUID]["device_info"].pop("last_drivelog")
    assert await _setup(hass, number, coordinator) == []
    assert _drive_buttons(await _setup(hass, button, coordinator)) == []


async def test_setpoint_number_reads_and_writes(hass, coordinator):
    """Setting the target sends the command and updates state optimistically."""
    from custom_components.fireboard.number import FireBoardDriveSetpointNumber

    entity = FireBoardDriveSetpointNumber(coordinator, UUID)
    assert entity.native_value == 225.0
    assert entity.native_unit_of_measurement == "°F"

    await entity.async_set_native_value(250)

    coordinator.client.set_drive_setpoint.assert_awaited_once_with(UUID, 250)
    drivelog = coordinator.data[UUID]["device_info"]["last_drivelog"]
    assert drivelog["setpoint"] == 250
    assert drivelog["modetype"] == 2
    assert "created" in drivelog


async def test_setpoint_unit_celsius_and_invalid(hass, coordinator):
    """Celsius devices get a Celsius control; junk setpoints read as None."""
    from custom_components.fireboard.number import FireBoardDriveSetpointNumber

    drivelog = coordinator.data[UUID]["device_info"]["last_drivelog"]
    drivelog["degreetype"] = 1
    drivelog["setpoint"] = "bad"
    entity = FireBoardDriveSetpointNumber(coordinator, UUID)
    assert entity.native_unit_of_measurement == "°C"
    assert entity.native_value is None


async def test_fan_speed_number_reads_and_writes(hass, coordinator):
    """Setting fan speed switches to manual."""
    from custom_components.fireboard.number import FireBoardDriveFanSpeedNumber

    entity = FireBoardDriveFanSpeedNumber(coordinator, UUID)
    assert entity.native_value == 42
    assert entity.extra_state_attributes == {"manual_mode": False}

    await entity.async_set_native_value(60)

    coordinator.client.set_drive_fan_speed.assert_awaited_once_with(UUID, 60)
    drivelog = coordinator.data[UUID]["device_info"]["last_drivelog"]
    assert drivelog["driveper"] == 0.6
    assert drivelog["modetype"] == 1
    assert entity.extra_state_attributes == {"manual_mode": True}


async def test_fan_speed_invalid(hass, coordinator):
    """Missing fan reading and unknown mode."""
    from custom_components.fireboard.number import FireBoardDriveFanSpeedNumber

    coordinator.data[UUID]["device_info"]["last_drivelog"] = {}
    entity = FireBoardDriveFanSpeedNumber(coordinator, UUID)
    assert entity.native_value is None
    assert entity.extra_state_attributes == {}


async def test_drive_off_button(hass, coordinator):
    """Pressing Drive Off sends the off command."""
    from custom_components.fireboard import button

    entities = _drive_buttons(await _setup(hass, button, coordinator))
    assert len(entities) == 1
    await entities[0].async_press()

    coordinator.client.turn_drive_off.assert_awaited_once_with(UUID)
    drivelog = coordinator.data[UUID]["device_info"]["last_drivelog"]
    assert drivelog["modetype"] == 0
    assert drivelog["setpoint"] == 0


async def test_command_failure_raises(hass, coordinator):
    """API errors become HomeAssistantError so the UI shows them."""
    coordinator.client.turn_drive_off.side_effect = (
        FireBoardApiClientCommunicationError("down")
    )
    from custom_components.fireboard.button import FireBoardDriveOffButton

    with pytest.raises(HomeAssistantError):
        await FireBoardDriveOffButton(coordinator, UUID).async_press()


async def test_command_for_unknown_device_is_noop(hass, coordinator):
    """No crash if the device vanished between command and state update."""
    called = AsyncMock()
    await coordinator.async_send_drive_command("nope", called, {"setpoint": 1})
    called.assert_awaited_once()


def _client_with_response(status=200, body=None, json_error=None):
    session = MagicMock()
    response = MagicMock()
    response.status = status
    response.raise_for_status = MagicMock()
    if json_error:
        response.json = AsyncMock(side_effect=json_error)
    else:
        response.json = AsyncMock(return_value=body)
    session.request = AsyncMock(return_value=response)
    client = FireBoardApiClient("a@b.c", "pw", session)
    client._token = "tok"
    client._cookie_jar = [MagicMock(key="sessionid", value="s")]
    return client, session


async def test_api_set_setpoint_payload():
    """Setpoint command matches the app's mq.json payload."""
    client, session = _client_with_response(body=None)
    await client.set_drive_setpoint(UUID, 225.0)

    method, url = session.request.call_args.args
    assert method == "POST"
    assert url.endswith(f"/devices/{UUID}/mq.json")
    assert session.request.call_args.kwargs["json"] == {
        "topic": "device",
        "payload": {"request_type": "control", "t": "fan", "setpoint": "225"},
    }


async def test_api_fractional_setpoint_and_off():
    """Fractional setpoints are kept; off sends setpoint 0."""
    client, session = _client_with_response(body={"ok": True})
    await client.set_drive_setpoint(UUID, 107.5)
    payload = session.request.call_args.kwargs["json"]["payload"]
    assert payload["setpoint"] == "107.5"

    await client.turn_drive_off(UUID)
    payload = session.request.call_args.kwargs["json"]["payload"]
    assert payload["setpoint"] == "0"


async def test_api_fan_speed_payload_is_ratio_and_clamped():
    """Fan speed is sent as a 0.00-1.00 ratio, clamped like the app."""
    client, session = _client_with_response(json_error=ValueError("no json"))
    await client.set_drive_fan_speed(UUID, 55)
    payload = session.request.call_args.kwargs["json"]["payload"]
    assert payload == {"request_type": "control", "t": "fan", "p": "0.55"}

    await client.set_drive_fan_speed(UUID, 150)
    assert session.request.call_args.kwargs["json"]["payload"]["p"] == "1.00"


async def test_drive_entities_added_when_drive_appears_later(hass, coordinator):
    """A Drive detected after setup gets its entities without a reload."""
    from custom_components.fireboard import number

    coordinator.data[UUID]["device_info"].pop("last_drivelog")
    entities: list = []
    entry = ConfigEntry(domain=DOMAIN)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await number.async_setup_entry(hass, entry, entities.extend)
    assert entities == []

    coordinator.data[UUID]["has_drive"] = True
    coordinator.async_set_updated_data(coordinator.data)
    assert len(entities) == 2

    # Further updates don't add duplicates.
    coordinator.async_set_updated_data(coordinator.data)
    assert len(entities) == 2


async def test_test_notification_button(hass, coordinator):
    """The device gets a test-notification button that works while offline."""
    from custom_components.fireboard import button

    entry = ConfigEntry(
        domain=DOMAIN, options={"notify_targets": ["persistent_notification"]}
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entities: list = []
    await button.async_setup_entry(hass, entry, entities.extend)
    test_button = next(
        e for e in entities if isinstance(e, button.FireBoardTestNotificationButton)
    )
    assert test_button.available is True
    assert test_button.unique_id == f"{UUID}_test_notification"

    test_button.hass = MagicMock()
    test_button.hass.services.async_call = AsyncMock()
    await test_button.async_press()
    call = test_button.hass.services.async_call.call_args
    assert call.args[:2] == ("persistent_notification", "create")

    test_button.hass.services.async_call.side_effect = RuntimeError("gone")
    with pytest.raises(HomeAssistantError, match="failed"):
        await test_button.async_press()

    entry.options = {}
    with pytest.raises(HomeAssistantError, match="No notification targets"):
        await test_button.async_press()
