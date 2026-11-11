"""Tests for the FireBoard options (settings) and reconfigure flows."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntry
from homeassistant.data_entry_flow import FlowResultType

from custom_components.fireboard.config_flow import (
    ConfigFlow,
    FireBoardOptionsFlow,
    get_option,
)
from custom_components.fireboard.const import (
    CONF_BATTERY_LOW_THRESHOLD,
    CONF_DRIVE_CONTROLS,
    CONF_NOTIFY_LIVE,
    CONF_NOTIFY_PROBE_ALERTS,
    CONF_NOTIFY_TARGETS,
    CONF_POLLING_INTERVAL,
    CONF_PROBE_ALERTS,
    DOMAIN,
)


def _options_flow(entry):
    flow = ConfigFlow.async_get_options_flow(entry)
    assert isinstance(flow, FireBoardOptionsFlow)
    flow.config_entry = entry
    return flow


async def test_options_opens_menu():
    """Configure opens a menu with the three settings pages."""
    entry = ConfigEntry(domain=DOMAIN)
    result = await _options_flow(entry).async_step_init()
    assert result["type"] == FlowResultType.MENU
    assert result["menu_options"] == [
        "general",
        "notifications",
        "probe_alerts",
        "test_notification",
    ]


async def test_general_form_and_save_keeps_other_options():
    """The General page saves typed values without dropping other pages."""
    entry = ConfigEntry(
        domain=DOMAIN,
        data={CONF_POLLING_INTERVAL: 90},
        options={CONF_NOTIFY_TARGETS: ["mobile_app_pixel"]},
    )
    flow = _options_flow(entry)
    result = await flow.async_step_general()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "general"

    result = await flow.async_step_general(
        {
            CONF_POLLING_INTERVAL: 60.0,
            CONF_BATTERY_LOW_THRESHOLD: 15.0,
            CONF_DRIVE_CONTROLS: False,
        }
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_NOTIFY_TARGETS: ["mobile_app_pixel"],
        CONF_POLLING_INTERVAL: 60,
        CONF_BATTERY_LOW_THRESHOLD: 15,
        CONF_DRIVE_CONTROLS: False,
    }


def _hass_with_notify(services):
    hass = MagicMock()
    hass.services.async_services.return_value = {"notify": dict.fromkeys(services)}
    return hass


async def test_notifications_lists_phones_and_saves():
    """Phones are offered by friendly name; choices are saved."""
    entry = ConfigEntry(domain=DOMAIN, options={CONF_NOTIFY_TARGETS: ["gone"]})
    flow = _options_flow(entry)
    flow.hass = _hass_with_notify(
        [
            "notify",
            "send_message",
            "persistent_notification",
            "mobile_app_claes_iphone",
            "telegram",
        ]
    )
    options = flow._notify_target_options()
    assert options == [
        {"value": "mobile_app_claes_iphone", "label": "Mobile app: Claes Iphone"},
        {"value": "telegram", "label": "Telegram"},
        {
            "value": "persistent_notification",
            "label": "Home Assistant persistent notifications",
        },
    ]

    result = await flow.async_step_notifications()
    assert result["type"] == FlowResultType.FORM
    assert result["description_placeholders"]["phone_hint"] == ""

    result = await flow.async_step_notifications(
        {CONF_NOTIFY_TARGETS: ["mobile_app_claes_iphone"], CONF_NOTIFY_LIVE: True}
    )
    assert result["data"][CONF_NOTIFY_TARGETS] == ["mobile_app_claes_iphone"]
    assert result["data"][CONF_NOTIFY_LIVE] is True
    assert result["data"][CONF_NOTIFY_PROBE_ALERTS] is False


async def test_notifications_hint_when_no_phone():
    """Without the Companion app, the page explains how to get one."""
    flow = _options_flow(ConfigEntry(domain=DOMAIN))
    flow.hass = _hass_with_notify([])
    result = await flow.async_step_notifications()
    assert "Companion app" in result["description_placeholders"]["phone_hint"]


async def test_probe_alerts_page(mock_coordinator_data):
    """One target and one minimum field per probe; empty fields aren't stored."""
    entry = ConfigEntry(
        domain=DOMAIN,
        entry_id="e1",
        options={CONF_PROBE_ALERTS: {"test-device-uuid-123:1": {"max": 63}}},
    )
    flow = _options_flow(entry)
    flow.hass = MagicMock()
    coordinator = MagicMock()
    coordinator.data = mock_coordinator_data
    flow.hass.data = {DOMAIN: {"e1": coordinator}}

    result = await flow.async_step_probe_alerts()
    assert result["type"] == FlowResultType.FORM
    assert list(flow._probe_fields) == [
        "Probe 1 – target",
        "Probe 1 – minimum",
        "Probe 2 – target",
        "Probe 2 – minimum",
        "Probe 3 – target",
        "Probe 3 – minimum",
    ]

    result = await flow.async_step_probe_alerts(
        {"Probe 1 – target": 65, "Probe 3 – minimum": 100.0, "Probe 2 – target": ""}
    )
    assert result["data"][CONF_PROBE_ALERTS] == {
        "test-device-uuid-123:1": {"max": 65.0},
        "test-device-uuid-123:3": {"min": 100.0},
    }


async def test_probe_alerts_labels_include_device_when_several(mock_coordinator_data):
    """With two devices, fields are prefixed with the device name."""
    second = {
        "device_info": {"title": "Smoker", "channels": [{"channel": 1}]},
    }
    mock_coordinator_data["other"] = second
    entry = ConfigEntry(domain=DOMAIN, entry_id="e1")
    flow = _options_flow(entry)
    flow.hass = MagicMock()
    flow.hass.data = {DOMAIN: {"e1": MagicMock(data=mock_coordinator_data)}}
    await flow.async_step_probe_alerts()
    assert "Smoker · Probe 1 – target" in flow._probe_fields
    assert "Test FireBoard · Probe 1 – target" in flow._probe_fields


async def test_probe_alerts_aborts_without_devices():
    """Nothing to configure before devices are loaded."""
    flow = _options_flow(ConfigEntry(domain=DOMAIN, entry_id="e1"))
    flow.hass = MagicMock()
    flow.hass.data = {}
    result = await flow.async_step_probe_alerts()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "no_probes"


def test_get_option_precedence():
    """Options beat legacy entry data, which beats the default."""
    entry = ConfigEntry(
        domain=DOMAIN,
        data={CONF_POLLING_INTERVAL: 90},
        options={CONF_POLLING_INTERVAL: 120},
    )
    assert get_option(entry, CONF_POLLING_INTERVAL, 40) == 120
    entry.options = {}
    assert get_option(entry, CONF_POLLING_INTERVAL, 40) == 90
    entry.data = {}
    assert get_option(entry, CONF_POLLING_INTERVAL, 40) == 40


async def test_coordinator_uses_options_polling_interval(hass):
    """The coordinator honors the polling interval from options."""
    from custom_components.fireboard.coordinator import (
        FireBoardDataUpdateCoordinator,
    )

    entry = ConfigEntry(
        domain=DOMAIN,
        data={"email": "a@b.c", "password": "x", CONF_POLLING_INTERVAL: 40},
        options={CONF_POLLING_INTERVAL: 120},
    )
    with patch(
        "custom_components.fireboard.coordinator.DataUpdateCoordinator.__init__",
        return_value=None,
    ) as init:
        FireBoardDataUpdateCoordinator(hass, entry)
    assert init.call_args.kwargs["update_interval"].total_seconds() == 120


def _reconfigure_flow(hass, entry):
    flow = ConfigFlow()
    flow.hass = hass
    flow.context = {"source": "reconfigure", "entry": entry}
    return flow


async def test_reconfigure_form(hass):
    """The reconfigure step shows a form first."""
    entry = ConfigEntry(domain=DOMAIN, data={"email": "a@b.c"}, unique_id="a@b.c")
    result = await _reconfigure_flow(hass, entry).async_step_reconfigure()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "reconfigure"


async def test_reconfigure_updates_password(hass):
    """Valid new credentials update the entry."""
    entry = ConfigEntry(
        domain=DOMAIN, data={"email": "a@b.c", "password": "old"}, unique_id="a@b.c"
    )
    with patch(
        "custom_components.fireboard.config_flow.FireBoardApiClient"
    ) as client_cls:
        client_cls.return_value = AsyncMock()
        client_cls.return_value.get_devices = AsyncMock(return_value=[])
        result = await _reconfigure_flow(hass, entry).async_step_reconfigure(
            {"email": "A@b.c", "password": "new"}
        )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["password"] == "new"


async def test_reconfigure_rejects_other_account(hass):
    """Switching to a different account aborts."""
    entry = ConfigEntry(domain=DOMAIN, data={"email": "a@b.c"}, unique_id="a@b.c")
    with patch(
        "custom_components.fireboard.config_flow.FireBoardApiClient"
    ) as client_cls:
        client_cls.return_value = AsyncMock()
        flow = _reconfigure_flow(hass, entry)
        try:
            await flow.async_step_reconfigure({"email": "x@y.z", "password": "p"})
        except Exception as err:  # mock raises AbortFlow, HA converts it
            assert getattr(err, "reason", None) == "wrong_account"
        else:
            raise AssertionError("expected abort")


async def test_reconfigure_invalid_auth(hass):
    """Bad credentials re-show the form with an error."""
    from custom_components.fireboard.api_client import (
        FireBoardApiClientAuthenticationError,
    )

    entry = ConfigEntry(domain=DOMAIN, data={"email": "a@b.c"}, unique_id="a@b.c")
    with patch(
        "custom_components.fireboard.config_flow.FireBoardApiClient"
    ) as client_cls:
        client_cls.return_value = AsyncMock()
        client_cls.return_value.authenticate.side_effect = (
            FireBoardApiClientAuthenticationError("bad")
        )
        result = await _reconfigure_flow(hass, entry).async_step_reconfigure(
            {"email": "a@b.c", "password": "bad"}
        )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_options_change_reloads_entry(hass):
    """The update listener reloads the config entry."""
    from custom_components.fireboard import _async_update_listener

    entry = ConfigEntry(domain=DOMAIN, entry_id="abc")
    await _async_update_listener(hass, entry)
    assert hass.config_entries.reloaded == ["abc"]


async def test_send_test_notification_from_menu():
    """The menu's test entry sends and reports per target."""
    entry = ConfigEntry(
        domain=DOMAIN,
        options={
            CONF_NOTIFY_TARGETS: ["mobile_app_claes_iphone", "persistent_notification"]
        },
    )
    flow = _options_flow(entry)
    flow.hass = _hass_with_notify(["mobile_app_claes_iphone"])
    flow.hass.services.async_call = AsyncMock()

    result = await flow.async_step_test_notification()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "test_sent"
    assert result["description_placeholders"]["delivered"] == (
        "Mobile app: Claes Iphone, Home Assistant persistent notifications"
    )
    sent = flow.hass.services.async_call.call_args_list[0]
    assert sent.args[2]["data"]["push"]["interruption-level"] == "time-sensitive"

    async def fail_phone(domain, service, data, **kwargs):
        if domain == "notify":
            raise RuntimeError("no such service")

    flow.hass.services.async_call = AsyncMock(side_effect=fail_phone)
    result = await flow.async_step_test_notification()
    assert result["reason"] == "test_failed"
    assert result["description_placeholders"] == {
        "delivered": "Home Assistant persistent notifications",
        "failed": "Mobile app: Claes Iphone",
    }


async def test_test_notification_without_targets():
    """No targets -> explain where to set them."""
    flow = _options_flow(ConfigEntry(domain=DOMAIN))
    flow.hass = _hass_with_notify([])
    result = await flow.async_step_test_notification()
    assert result["reason"] == "no_targets"


async def test_probe_alerts_reject_out_of_range(mock_coordinator_data):
    """Negative or >1000 temperatures are refused, like in the FireBoard app."""
    entry = ConfigEntry(domain=DOMAIN, entry_id="e1")
    flow = _options_flow(entry)
    flow.hass = MagicMock()
    flow.hass.data = {DOMAIN: {"e1": MagicMock(data=mock_coordinator_data)}}
    await flow.async_step_probe_alerts()

    result = await flow.async_step_probe_alerts(
        {"Probe 1 – minimum": -5, "Probe 2 – target": 1200, "Probe 3 – target": 70}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {
        "Probe 1 – minimum": "temperature_out_of_range",
        "Probe 2 – target": "temperature_out_of_range",
    }

    result = await flow.async_step_probe_alerts({"Probe 1 – minimum": 0})
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PROBE_ALERTS] == {"test-device-uuid-123:1": {"min": 0.0}}
