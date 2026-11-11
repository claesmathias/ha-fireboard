"""Built-in notifications for FireBoard, configured from the options dialog.

Mirrors the FireBoard app's own alerts (probe above target / below minimum)
and adds a few Home Assistant extras: a live cook notification that updates
in place, Drive lid-open, device offline and low battery alerts.

Alerts fire when a value *crosses* its threshold, never on the first value
seen after startup -- otherwise every Home Assistant restart (or settings
change, which reloads the integration) would re-send alerts for a cook
that's already done.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_BATTERY_LOW_THRESHOLD,
    CONF_NOTIFY_BATTERY,
    CONF_NOTIFY_LID,
    CONF_NOTIFY_LIVE,
    CONF_NOTIFY_OFFLINE,
    CONF_NOTIFY_PROBE_ALERTS,
    CONF_NOTIFY_TARGETS,
    CONF_PROBE_ALERTS,
    DEFAULT_BATTERY_LOW_THRESHOLD,
    NOTIFY_TARGET_PERSISTENT,
)
from .util import drive_mode

_LOGGER = logging.getLogger(__name__)

# Degrees a probe must move back past its threshold before the alert can
# fire again, so a reading hovering around the target doesn't spam.
HYSTERESIS = 1.0

ALERT_DATA = {
    # iOS: break through Focus modes. Android: heads-up, delivered at once.
    "push": {"interruption-level": "time-sensitive"},
    "priority": "high",
    "ttl": 0,
    "channel": "FireBoard alerts",
}
LIVE_DATA = {
    # Update silently in place; Android keeps it pinned while cooking.
    "push": {"interruption-level": "passive"},
    "alert_once": True,
    "sticky": True,
    "persistent": True,
    "channel": "FireBoard live",
}


def probe_key(device_uuid: str, channel: int) -> str:
    """Return the options key used to store one probe's alert settings."""
    return f"{device_uuid}:{channel}"


def app_alert_thresholds(channel_config: dict[str, Any]) -> tuple[Any, Any]:
    """Return (min, max) from the alerts configured in the FireBoard app."""
    low = high = None
    for alert in channel_config.get("alerts") or []:
        if not isinstance(alert, dict):
            continue
        if low is None and alert.get("temp_min") is not None:
            low = alert["temp_min"]
        if high is None and alert.get("temp_max") is not None:
            high = alert["temp_max"]
    return low, high


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: float | None, unit: str) -> str:
    if value is None:
        return "–"
    return f"{value:.0f}{unit}"


@dataclass
class _ProbeState:
    """Edge-detection state for one probe."""

    high_armed: bool | None = None  # None = no reading seen yet
    low_armed: bool | None = None


@dataclass
class _DeviceState:
    """Edge-detection state for one device."""

    online: bool | None = None
    lid_paused: bool | None = None
    battery_low: bool | None = None
    live_message: str | None = None
    probes: dict[int, _ProbeState] = field(default_factory=dict)


class FireBoardNotifier:
    """Send notifications based on coordinator data and the entry's options."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator) -> None:
        """Initialize the notifier."""
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self._devices: dict[str, _DeviceState] = {}

    @property
    def _options(self) -> dict[str, Any]:
        return dict(self.entry.options or {})

    @property
    def targets(self) -> list[str]:
        """Return the notify targets chosen in the options."""
        return list(self._options.get(CONF_NOTIFY_TARGETS) or [])

    @callback
    def async_handle_update(self) -> None:
        """Coordinator listener: evaluate alerts on every data update."""
        if not self.targets or not self.coordinator.data:
            return
        self.hass.async_create_task(self.async_process())

    async def async_process(self) -> None:
        """Check every device for alert conditions and send notifications."""
        options = self._options
        for device_uuid, data in (self.coordinator.data or {}).items():
            state = self._devices.setdefault(device_uuid, _DeviceState())
            device_info = data.get("device_info", {})
            title = device_info.get("title") or "FireBoard"

            online = bool(data.get("online"))
            if options.get(CONF_NOTIFY_OFFLINE) and state.online and not online:
                await self._send(
                    f"{title} is offline",
                    "FireBoard Cloud has not received data from the device for "
                    "several minutes. Check its power supply and WiFi connection.",
                    tag=f"fireboard_{device_uuid}_offline",
                )
            if state.online is False and online:
                await self._clear(f"fireboard_{device_uuid}_offline")
            state.online = online

            if options.get(CONF_NOTIFY_PROBE_ALERTS):
                await self._check_probes(device_uuid, data, state, title)

            if options.get(CONF_NOTIFY_LID):
                await self._check_lid(device_uuid, data, state, title)

            if options.get(CONF_NOTIFY_BATTERY):
                await self._check_battery(device_uuid, data, state, title)

            if options.get(CONF_NOTIFY_LIVE):
                await self._update_live(device_uuid, data, state, title)

    async def _check_probes(
        self,
        device_uuid: str,
        data: dict[str, Any],
        state: _DeviceState,
        title: str,
    ) -> None:
        overrides = self._options.get(CONF_PROBE_ALERTS) or {}
        readings = {
            ch.get("channel"): ch
            for ch in data.get("temperatures", {}).get("channels", [])
        }
        for channel_config in data.get("device_info", {}).get("channels", []):
            channel = channel_config.get("channel")
            if channel is None:
                continue
            reading = readings.get(channel) or {}
            temp = _to_float(reading.get("current_temp"))
            if temp is None:
                continue

            key = probe_key(device_uuid, channel)
            if key in overrides:
                low = _to_float(overrides[key].get("min"))
                high = _to_float(overrides[key].get("max"))
            else:
                app_low, app_high = app_alert_thresholds(channel_config)
                low, high = _to_float(app_low), _to_float(app_high)

            unit = "°C" if reading.get("degreetype") == 1 else "°F"
            label = channel_config.get("channel_label") or f"Probe {channel}"
            probe = state.probes.setdefault(channel, _ProbeState())

            if high is not None:
                if temp >= high:
                    if probe.high_armed:
                        await self._send(
                            f"{label} reached target temperature",
                            f"{title}: {label} is at {_fmt(temp, unit)} "
                            f"(target {_fmt(high, unit)}).",
                            tag=f"fireboard_{device_uuid}_{channel}_high",
                        )
                    probe.high_armed = False
                elif temp <= high - HYSTERESIS or probe.high_armed is None:
                    probe.high_armed = True

            if low is not None:
                if temp < low:
                    if probe.low_armed:
                        await self._send(
                            f"{label} below minimum temperature",
                            f"{title}: {label} is at {_fmt(temp, unit)} "
                            f"(minimum {_fmt(low, unit)}).",
                            tag=f"fireboard_{device_uuid}_{channel}_low",
                        )
                    probe.low_armed = False
                elif temp >= low + HYSTERESIS:
                    probe.low_armed = True

    async def _check_lid(
        self,
        device_uuid: str,
        data: dict[str, Any],
        state: _DeviceState,
        title: str,
    ) -> None:
        drive_status = data.get("drive_status") or {}
        paused = bool(drive_status.get("lid_paused"))
        if state.lid_paused is False and paused:
            await self._send(
                "Drive paused",
                f"{title}: the FireBoard Drive has paused the fan because the "
                "lid is open.",
                tag=f"fireboard_{device_uuid}_lid",
            )
        if state.lid_paused and not paused:
            await self._clear(f"fireboard_{device_uuid}_lid")
        state.lid_paused = paused

    async def _check_battery(
        self,
        device_uuid: str,
        data: dict[str, Any],
        state: _DeviceState,
        title: str,
    ) -> None:
        reading = _to_float(data.get("device_info", {}).get("last_battery_reading"))
        if reading is None:
            return
        percent = round(reading * 100)
        threshold = self._options.get(
            CONF_BATTERY_LOW_THRESHOLD, DEFAULT_BATTERY_LOW_THRESHOLD
        )
        low = percent < threshold
        if state.battery_low is False and low:
            await self._send(
                f"{title} battery low",
                f"Battery level is {percent}%.",
                tag=f"fireboard_{device_uuid}_battery",
            )
        state.battery_low = low

    async def _update_live(
        self,
        device_uuid: str,
        data: dict[str, Any],
        state: _DeviceState,
        title: str,
    ) -> None:
        tag = f"fireboard_live_{device_uuid}"
        message = live_message(data) if data.get("online") else None

        if message is None:
            if state.live_message is not None:
                await self._clear(tag)
                state.live_message = None
            return

        if message == state.live_message:
            return
        session = data.get("session") or {}
        active = bool(session) and session.get("end_time") is None
        live_title = (session.get("title") if active else None) or title
        await self._send(live_title, message, tag=tag, live=True)
        state.live_message = message

    async def async_send_test(self) -> tuple[list[str], list[str]]:
        """Send a test alert to every configured target.

        Uses the same delivery settings as a real probe alert, so it also
        shows whether time-sensitive alerts get through Focus / Do Not
        Disturb. Returns (delivered, failed) target lists.
        """
        failed = await self._send(
            "FireBoard test notification",
            "Notifications from the FireBoard integration are configured " "correctly.",
            tag="fireboard_test",
        )
        delivered = [t for t in self.targets if t not in failed]
        return delivered, failed

    async def _send(
        self, title: str, message: str, *, tag: str, live: bool = False
    ) -> list[str]:
        """Send to every target; return the targets that failed."""
        extra = LIVE_DATA if live else ALERT_DATA
        failed: list[str] = []
        for target in self.targets:
            try:
                if target == NOTIFY_TARGET_PERSISTENT:
                    await self.hass.services.async_call(
                        "persistent_notification",
                        "create",
                        {"title": title, "message": message, "notification_id": tag},
                        blocking=True,
                    )
                else:
                    await self.hass.services.async_call(
                        "notify",
                        target,
                        {
                            "title": title,
                            "message": message,
                            "data": {"tag": tag, **extra},
                        },
                        blocking=True,
                    )
            except Exception as err:  # pylint: disable=broad-except
                failed.append(target)
                _LOGGER.warning(
                    "Could not send FireBoard notification to %s: %s", target, err
                )
        return failed

    async def _clear(self, tag: str) -> None:
        for target in self.targets:
            try:
                if target == NOTIFY_TARGET_PERSISTENT:
                    await self.hass.services.async_call(
                        "persistent_notification", "dismiss", {"notification_id": tag}
                    )
                elif target.startswith("mobile_app_"):
                    await self.hass.services.async_call(
                        "notify",
                        target,
                        {"message": "clear_notification", "data": {"tag": tag}},
                    )
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.debug("Could not clear FireBoard notification: %s", err)


def live_message(data: dict[str, Any]) -> str | None:
    """Build the one-line live cook summary, or None if nothing is reading."""
    readings = {
        ch.get("channel"): ch for ch in data.get("temperatures", {}).get("channels", [])
    }
    parts: list[str] = []
    unit = "°F"
    for channel_config in data.get("device_info", {}).get("channels", []):
        channel = channel_config.get("channel")
        reading = readings.get(channel) or {}
        temp = _to_float(reading.get("current_temp"))
        if temp is None:
            continue
        unit = "°C" if reading.get("degreetype") == 1 else "°F"
        label = channel_config.get("channel_label") or f"Probe {channel}"
        parts.append(f"{label} {_fmt(temp, unit)}")

    if not parts:
        return None

    drivelog = data.get("device_info", {}).get("last_drivelog") or {}
    mode = drive_mode(drivelog)
    if mode == "Auto":
        fan = _to_float(drivelog.get("driveper"))
        parts.append(
            f"Drive target {_fmt(_to_float(drivelog.get('setpoint')), unit)}"
            + (f" (fan {fan * 100:.0f}%)" if fan is not None else "")
        )
    elif mode == "Manual":
        fan = _to_float(drivelog.get("driveper")) or 0
        parts.append(f"Drive fan {fan * 100:.0f}%")

    return ", ".join(parts)
