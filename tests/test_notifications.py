"""Tests for FireBoard's built-in notifications."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import ConfigEntry

from custom_components.fireboard.const import (
    CONF_NOTIFY_BATTERY,
    CONF_NOTIFY_LID,
    CONF_NOTIFY_LIVE,
    CONF_NOTIFY_OFFLINE,
    CONF_NOTIFY_PROBE_ALERTS,
    CONF_NOTIFY_TARGETS,
    CONF_PROBE_ALERTS,
    DOMAIN,
)
from custom_components.fireboard.notifications import (
    FireBoardNotifier,
    app_alert_thresholds,
    live_message,
)

UUID = "dev-1"


def _data(temps=None, online=True, **extra):
    temps = temps or {}
    device = {
        "device_info": {
            "title": "Kamado",
            "channels": [
                {"channel": 1, "channel_label": "Brisket"},
                {"channel": 2, "channel_label": "Grill"},
            ],
            "last_battery_reading": extra.pop("battery", None),
            "last_drivelog": extra.pop("drivelog", None),
        },
        "temperatures": {
            "channels": [
                {"channel": ch, "current_temp": t, "degreetype": 1}
                for ch, t in temps.items()
            ]
        },
        "online": online,
        **extra,
    }
    return {UUID: device}


@pytest.fixture
def setup():
    """Return (notifier, coordinator, service-call mock)."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    entry = ConfigEntry(
        domain=DOMAIN,
        options={
            CONF_NOTIFY_TARGETS: ["mobile_app_phone", "persistent_notification"],
            CONF_NOTIFY_PROBE_ALERTS: True,
            CONF_NOTIFY_LID: True,
            CONF_NOTIFY_OFFLINE: True,
            CONF_NOTIFY_BATTERY: True,
            CONF_PROBE_ALERTS: {f"{UUID}:1": {"max": 90}, f"{UUID}:2": {"min": 100}},
        },
    )
    coordinator = MagicMock()
    return FireBoardNotifier(hass, entry, coordinator), coordinator, hass


async def _run(notifier, coordinator, data):
    coordinator.data = data
    await notifier.async_process()


def _titles(hass):
    return [
        c.args[2].get("title")
        for c in hass.services.async_call.call_args_list
        if c.args[0] == "notify" and "title" in c.args[2]
    ]


async def test_probe_target_fires_once_on_crossing(setup):
    """Reaching the target notifies once; dropping back re-arms it."""
    notifier, coordinator, hass = setup
    await _run(notifier, coordinator, _data({1: 80, 2: 120}))
    assert hass.services.async_call.await_count == 0

    await _run(notifier, coordinator, _data({1: 91, 2: 120}))
    assert _titles(hass) == ["Brisket reached target temperature"]
    call = hass.services.async_call.call_args_list[0]
    assert call.args[2]["message"] == "Kamado: Brisket is at 91°C (target 90°C)."
    assert call.args[1] == "mobile_app_phone"
    assert call.args[2]["data"]["tag"] == f"fireboard_{UUID}_1_high"
    assert call.args[2]["data"]["push"]["interruption-level"] == "time-sensitive"
    # ...and the sidebar notification
    persistent = hass.services.async_call.call_args_list[1]
    assert persistent.args[:2] == ("persistent_notification", "create")

    await _run(notifier, coordinator, _data({1: 95, 2: 120}))
    assert len(_titles(hass)) == 1  # no repeat

    await _run(notifier, coordinator, _data({1: 85, 2: 120}))
    await _run(notifier, coordinator, _data({1: 92, 2: 120}))
    assert len(_titles(hass)) == 2  # re-armed after dropping back


async def test_already_past_target_at_startup_is_silent(setup):
    """A restart mid-cook doesn't re-send alerts for a finished probe."""
    notifier, coordinator, hass = setup
    await _run(notifier, coordinator, _data({1: 95, 2: 50}))
    await _run(notifier, coordinator, _data({1: 96, 2: 40}))
    assert _titles(hass) == []


async def test_minimum_fires_when_dropping(setup):
    """A grill dropping below its minimum notifies."""
    notifier, coordinator, hass = setup
    await _run(notifier, coordinator, _data({2: 120}))
    await _run(notifier, coordinator, _data({2: 95}))
    assert _titles(hass) == ["Grill below minimum temperature"]


async def test_app_alerts_used_without_override(setup):
    """Without HA thresholds, the FireBoard app's alerts apply."""
    notifier, coordinator, hass = setup
    notifier.entry.options[CONF_PROBE_ALERTS] = {}
    data = _data({1: 50})
    data[UUID]["device_info"]["channels"][0]["alerts"] = [{"temp_max": 60}]
    await _run(notifier, coordinator, data)
    data = _data({1: 61})
    data[UUID]["device_info"]["channels"][0]["alerts"] = [{"temp_max": 60}]
    await _run(notifier, coordinator, data)
    assert _titles(hass) == ["Brisket reached target temperature"]


async def test_offline_lid_and_battery(setup):
    """Offline, lid-open and low battery each notify on transition."""
    notifier, coordinator, hass = setup
    await _run(
        notifier,
        coordinator,
        _data({1: 50}, battery=0.5, drive_status={"lid_paused": False}),
    )
    await _run(
        notifier,
        coordinator,
        _data({1: 50}, battery=0.1, drive_status={"lid_paused": True}),
    )
    await _run(notifier, coordinator, _data(online=False))
    assert _titles(hass) == [
        "Drive paused",
        "Kamado battery low",
        "Kamado is offline",
    ]

    hass.services.async_call.reset_mock()
    await _run(notifier, coordinator, _data({1: 50}, drive_status={}))
    cleared = [c.args for c in hass.services.async_call.call_args_list]
    assert (
        "persistent_notification",
        "dismiss",
        {"notification_id": f"fireboard_{UUID}_offline"},
    ) in cleared


async def test_lid_closing_clears_notification(setup):
    """When the lid closes again, the lid notification is removed."""
    notifier, coordinator, hass = setup
    await _run(notifier, coordinator, _data({1: 50}, drive_status={"lid_paused": True}))
    await _run(
        notifier, coordinator, _data({1: 50}, drive_status={"lid_paused": False})
    )
    msgs = [c.args[2] for c in hass.services.async_call.call_args_list]
    assert {
        "message": "clear_notification",
        "data": {"tag": f"fireboard_{UUID}_lid"},
    } in msgs


async def test_live_notification_updates_and_clears(setup):
    """Live summary is sent on change only, and cleared when offline."""
    notifier, coordinator, hass = setup
    notifier.entry.options = {
        CONF_NOTIFY_TARGETS: ["mobile_app_phone"],
        CONF_NOTIFY_LIVE: True,
    }
    session = {"title": "Brisket Sunday", "end_time": None}
    await _run(notifier, coordinator, _data({1: 70, 2: 110}, session=session))
    call = hass.services.async_call.call_args_list[-1]
    assert call.args[2]["title"] == "Brisket Sunday"
    assert call.args[2]["message"] == "Brisket 70°C, Grill 110°C"
    assert call.args[2]["data"]["alert_once"] is True

    await _run(notifier, coordinator, _data({1: 70, 2: 110}, session=session))
    assert hass.services.async_call.await_count == 1  # unchanged -> not resent

    await _run(notifier, coordinator, _data({1: 71, 2: 110}))
    assert hass.services.async_call.call_args_list[-1].args[2]["title"] == "Kamado"

    await _run(notifier, coordinator, _data(online=False))
    assert hass.services.async_call.call_args_list[-1].args[2] == {
        "message": "clear_notification",
        "data": {"tag": f"fireboard_live_{UUID}"},
    }


async def test_send_failures_are_logged_not_raised(setup):
    """A broken notify target never breaks the integration."""
    notifier, coordinator, hass = setup
    hass.services.async_call.side_effect = RuntimeError("no such service")
    await _run(notifier, coordinator, _data({1: 80}))
    await _run(notifier, coordinator, _data({1: 95}))
    await notifier._clear("x")


def test_handle_update_schedules_only_with_targets(setup):
    """No targets configured -> nothing is scheduled."""
    notifier, coordinator, hass = setup
    coordinator.data = _data({1: 1})
    notifier.async_handle_update()
    assert hass.async_create_task.call_count == 1
    hass.async_create_task.call_args.args[0].close()

    notifier.entry.options = {}
    notifier.async_handle_update()
    assert hass.async_create_task.call_count == 1


def test_live_message_with_drive():
    """The live summary includes the Drive's target and fan."""
    data = _data(
        {1: 70},
        drivelog={"modetype": 2, "setpoint": 110, "driveper": 0.35},
    )[UUID]
    assert live_message(data) == "Brisket 70°C, Drive target 110°C (fan 35%)"
    data["device_info"]["last_drivelog"] = {"modetype": 1, "driveper": 0.5}
    assert live_message(data) == "Brisket 70°C, Drive fan 50%"
    assert live_message(_data()[UUID]) is None


def test_app_alert_thresholds():
    """Read min/max from the app's alert list, skipping junk."""
    assert app_alert_thresholds(
        {"alerts": ["x", {"temp_min": 1}, {"temp_max": 9}]}
    ) == (
        1,
        9,
    )
    assert app_alert_thresholds({}) == (None, None)
