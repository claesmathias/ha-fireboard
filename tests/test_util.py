"""Tests for FireBoard data interpretation helpers (rules from the app)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from custom_components.fireboard.util import (
    drive_mode,
    is_device_online,
    parse_timestamp,
    seconds_since,
    wifi_signal_percent,
)

NOW = datetime(2026, 11, 7, 12, 0, 0, tzinfo=timezone.utc)


def _ago(seconds: int) -> str:
    return (NOW - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_parse_timestamp_formats():
    """ISO and the device's own 'yyyy-MM-dd HH:mm:ss z' formats both parse."""
    expected = datetime(2026, 8, 9, 13, 15, 4, tzinfo=timezone.utc)
    assert parse_timestamp("2026-08-09T13:15:04Z") == expected
    assert parse_timestamp("2026-08-09 13:15:04 UTC") == expected
    assert parse_timestamp("2026-08-09 13:15:04+0000") == expected
    assert parse_timestamp("2026-08-09 13:15:04") == expected
    assert parse_timestamp("not a date") is None
    assert parse_timestamp(None) is None
    assert parse_timestamp("") is None


def test_seconds_since():
    """Age is computed against the supplied clock."""
    assert seconds_since(_ago(30), NOW) == 30
    assert seconds_since("garbage", NOW) is None


def test_online_from_fresh_device_log():
    """A device log newer than 310s means online."""
    assert is_device_online({"device_log": {"date": _ago(100)}}, NOW)


def test_offline_from_stale_activity():
    """Activity older than 310s means offline."""
    device = {
        "device_log": {"date": _ago(600)},
        "channels": [{"channel": 1, "last_templog": {"created": _ago(400)}}],
    }
    assert not is_device_online(device, NOW)


def test_online_uses_newest_timestamp():
    """Any fresh source (here a drivelog) is enough."""
    device = {
        "device_log": {"date": _ago(900)},
        "last_drivelog": {"created": _ago(20)},
        "latest_temps": [{"created": _ago(2000)}, "junk"],
    }
    assert is_device_online(device, NOW)


def test_online_from_live_current_temp():
    """current_temp is only present while live, so it implies online."""
    device = {"channels": [{"channel": 1, "current_temp": 150.0}]}
    assert is_device_online(device, NOW)


def test_offline_when_never_reported():
    """A powered-off device has all activity fields null."""
    device = {
        "device_log": None,
        "last_templog": None,
        "last_drivelog": None,
        "channels": [{"channel": 1, "last_templog": None}],
    }
    assert not is_device_online(device, NOW)


def test_online_when_timestamps_unparseable():
    """Don't mark devices unavailable just because a date format changed."""
    assert is_device_online({"device_log": {"date": "??"}}, NOW)


def test_drive_mode_mapping():
    """Map modetype 0/1/2 to Off/Manual/Auto."""
    assert drive_mode({"modetype": 2, "setpoint": 225, "driveper": 0.3}) == "Auto"
    assert drive_mode({"modetype": 1, "setpoint": 0, "driveper": 0.5}) == "Manual"
    assert drive_mode({"modetype": 0, "setpoint": 225, "driveper": 0}) == "Off"
    assert drive_mode({"modetype": "2", "setpoint": "225"}) == "Auto"


def test_drive_mode_zero_setpoint_and_fan_is_off():
    """The app shows Off when both setpoint and fan are 0."""
    assert drive_mode({"modetype": 2, "setpoint": 0, "driveper": 0}) == "Off"


def test_drive_mode_unknown():
    """Missing/invalid modetype yields None."""
    assert drive_mode(None) is None
    assert drive_mode({}) is None
    assert drive_mode({"modetype": "x"}) is None
    assert drive_mode({"modetype": 7, "setpoint": 1}) is None
    assert drive_mode({"modetype": 2, "setpoint": "bad"}) == "Auto"


def test_wifi_signal_percent():
    """Matches FBDevice.getSignalStrengthPercent."""
    assert wifi_signal_percent(-40) == 100
    assert wifi_signal_percent(-60) == 80
    assert wifi_signal_percent(-75) == 50
    assert wifi_signal_percent(-110) == 0
    assert wifi_signal_percent(0) is None
    assert wifi_signal_percent(None) is None
    assert wifi_signal_percent("x") is None


def test_drive_mode_accepts_strings_from_session_detail():
    """Session detail reports modetype as FireBoard's own label."""
    assert drive_mode({"modetype": "Auto", "setpoint": 140}) == "Auto"
    assert drive_mode({"modetype": "manual", "driveper": 0.5}) == "Manual"
    assert drive_mode({"modetype": "Turbo", "setpoint": 1}) is None


def test_drive_mode_stale_drivelog_is_off():
    """A Drive that stopped reporting is Off, like in the app."""
    fresh = {"modetype": 2, "setpoint": 140, "created": _ago(30)}
    stale = {"modetype": 2, "setpoint": 140, "created": _ago(3600)}
    assert drive_mode(fresh, NOW) == "Auto"
    assert drive_mode(stale, NOW) == "Off"
