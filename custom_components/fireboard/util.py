"""Helpers for interpreting FireBoard API data.

The rules here mirror the official FireBoard Android app (v4.5.2), since
FireBoard doesn't document these fields publicly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# The app treats a device as offline once its newest device_log is older
# than this many seconds (FBDevice.setDeviceLog).
DEVICE_ONLINE_MAX_AGE_SECONDS = 310

# Drive "modetype" values, from the app's Drive widget (setDriveMode /
# getDriveMode): 0 = Off, 1 = Manual (fixed fan speed), 2 = Auto (setpoint).
DRIVE_MODE_OFF = "Off"
DRIVE_MODE_MANUAL = "Manual"
DRIVE_MODE_AUTO = "Auto"
DRIVE_MODETYPES: dict[int, str] = {
    0: DRIVE_MODE_OFF,
    1: DRIVE_MODE_MANUAL,
    2: DRIVE_MODE_AUTO,
}

_FALLBACK_FORMATS = (
    "%Y-%m-%d %H:%M:%S %Z",
    "%Y-%m-%d %H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S",
)


def parse_timestamp(value: Any) -> datetime | None:
    """Parse a FireBoard timestamp into an aware UTC datetime.

    REST endpoints use ISO-8601 ("2026-08-09T13:15:04Z"); device logs and
    drivelogs relayed from the device may instead use
    "yyyy-MM-dd HH:mm:ss z". Naive timestamps are assumed to be UTC.
    """
    if not isinstance(value, str) or not value:
        return None

    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        for fmt in _FALLBACK_FORMATS:
            try:
                parsed = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue

    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def seconds_since(value: Any, now: datetime | None = None) -> float | None:
    """Return how many seconds ago a FireBoard timestamp was, if parseable."""
    parsed = parse_timestamp(value)
    if parsed is None:
        return None
    now = now or datetime.now(timezone.utc)
    return (now - parsed).total_seconds()


def device_activity_timestamps(device: dict[str, Any]) -> list[Any]:
    """Collect every "last heard from" timestamp devices.json offers."""
    timestamps: list[Any] = []

    device_log = device.get("device_log") or {}
    timestamps.append(device_log.get("date"))

    timestamps.append((device.get("last_templog") or {}).get("created"))
    timestamps.append((device.get("last_drivelog") or {}).get("created"))

    for channel in device.get("channels") or []:
        timestamps.append((channel.get("last_templog") or {}).get("created"))

    for reading in device.get("latest_temps") or []:
        if isinstance(reading, dict):
            timestamps.append(reading.get("created"))

    return [ts for ts in timestamps if ts]


def is_device_online(device: dict[str, Any], now: datetime | None = None) -> bool:
    """Decide whether a device is currently connected to FireBoard Cloud.

    Online if any channel has a live current_temp, or FireBoard has heard
    from it (device log, temperature log or drivelog) within
    DEVICE_ONLINE_MAX_AGE_SECONDS. If devices.json carries
    timestamps we can't parse, assume online rather than wrongly marking
    every entity unavailable.
    """
    # FireBoard only populates a channel's "current_temp" in devices.json
    # while the reading is under 60 seconds old, so its presence alone
    # proves the device is reporting.
    if any(
        channel.get("current_temp") is not None
        for channel in device.get("channels") or []
    ):
        return True

    timestamps = device_activity_timestamps(device)
    ages = [seconds_since(ts, now) for ts in timestamps]
    parsed_ages = [age for age in ages if age is not None]

    if parsed_ages:
        return min(parsed_ages) <= DEVICE_ONLINE_MAX_AGE_SECONDS
    if timestamps:
        # Timestamps present but in an unknown format.
        return True
    # Never reported anything (e.g. powered off): last_templog, device_log
    # and last_drivelog are all null in that case.
    return False


def drive_mode(
    drivelog: dict[str, Any] | None, now: datetime | None = None
) -> str | None:
    """Map a drivelog to the Drive's mode, the way the app's Drive widget does.

    Accepts devices.json's integer modetype or session detail's string
    ("Auto"/"Manual"/"Off"). Returns None when there is no usable modetype.
    The Drive counts as Off when commanded to a 0 setpoint with the fan at
    0%, or when its drivelog is stale (the app uses the same rule, since a
    Drive that stopped reporting is no longer driving the fan).
    """
    if not drivelog:
        return None

    raw = drivelog.get("modetype")
    mode: str | None
    if isinstance(raw, str) and raw.strip().capitalize() in DRIVE_MODETYPES.values():
        mode = raw.strip().capitalize()
    else:
        try:
            mode = DRIVE_MODETYPES.get(int(raw))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
    if mode is None:
        return None

    age = seconds_since(drivelog.get("created"), now)
    if age is not None and age > DEVICE_ONLINE_MAX_AGE_SECONDS:
        return DRIVE_MODE_OFF

    try:
        setpoint = float(drivelog.get("setpoint") or 0)
        fan = float(drivelog.get("driveper") or 0)
    except (TypeError, ValueError):
        setpoint = fan = None

    if setpoint == 0 and fan == 0:
        return DRIVE_MODE_OFF

    return mode


def wifi_signal_percent(signal_level: Any) -> int | None:
    """Convert a WiFi RSSI (dBm) to the 0-100% strength the app displays."""
    try:
        dbm = float(signal_level)
    except (TypeError, ValueError):
        return None
    if dbm == 0:
        # 0 means "no reading" on FireBoard devices.
        return None
    if dbm > -50:
        return 100
    return int(max(0.0, min(100.0, (100 + dbm) * 2)))
