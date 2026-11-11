"""Number platform for FireBoard integration: FireBoard Drive control."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DRIVE_CONTROLS,
    DEFAULT_DRIVE_CONTROLS,
    DOMAIN,
    TEMPERATURE_MAX,
    TEMPERATURE_MIN,
)
from .coordinator import FireBoardDataUpdateCoordinator
from .entity import FireBoardEntity, async_add_drive_entities
from .util import DRIVE_MODE_MANUAL, drive_mode


def drive_controls_enabled(config_entry: ConfigEntry) -> bool:
    """Return whether the user allowed Drive control from Home Assistant."""
    options = getattr(config_entry, "options", None) or {}
    return bool(options.get(CONF_DRIVE_CONTROLS, DEFAULT_DRIVE_CONTROLS))


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FireBoard Drive number entities."""
    if not drive_controls_enabled(config_entry):
        return

    coordinator: FireBoardDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]

    async_add_drive_entities(
        coordinator,
        config_entry,
        async_add_entities,
        lambda device_uuid: [
            FireBoardDriveSetpointNumber(coordinator, device_uuid),
            FireBoardDriveFanSpeedNumber(coordinator, device_uuid),
        ],
    )


class _FireBoardDriveNumber(FireBoardEntity, NumberEntity):
    """Shared helpers for FireBoard Drive controls."""

    _attr_mode = NumberMode.BOX

    @property
    def _drivelog(self) -> dict[str, Any]:
        return self._device_data.get("device_info", {}).get("last_drivelog") or {}


class FireBoardDriveSetpointNumber(_FireBoardDriveNumber):
    """Target pit temperature for a FireBoard Drive (Auto mode).

    Setting a value switches the Drive to Auto; setting 0 turns it off,
    which is exactly how the FireBoard app's "Off" works.
    """

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_icon = "mdi:thermometer-auto"
    # The FireBoard app clamps setpoints to 0-1000 in the device's unit.
    _attr_native_min_value = TEMPERATURE_MIN
    _attr_native_max_value = TEMPERATURE_MAX
    _attr_native_step = 1

    def __init__(
        self,
        coordinator: FireBoardDataUpdateCoordinator,
        device_uuid: str,
    ) -> None:
        """Initialize the Drive setpoint control."""
        super().__init__(coordinator, device_uuid)
        self._attr_unique_id = f"{device_uuid}_drive_setpoint_control"
        self._attr_name = f"{self._device_title} Drive Target Temperature"

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit the device's Drive works in."""
        degreetype = self._drivelog.get("degreetype") or self._device_data.get(
            "device_info", {}
        ).get("degreetype")
        if degreetype == 1:
            return UnitOfTemperature.CELSIUS
        return UnitOfTemperature.FAHRENHEIT

    @property
    def native_value(self) -> float | None:
        """Return the current setpoint."""
        try:
            return float(self._drivelog.get("setpoint"))
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Send a new setpoint to the Drive."""
        await self.coordinator.async_send_drive_command(
            self._device_uuid,
            lambda: self.coordinator.client.set_drive_setpoint(
                self._device_uuid, value
            ),
            {"setpoint": value, "modetype": 2 if value else 0},
        )


class FireBoardDriveFanSpeedNumber(_FireBoardDriveNumber):
    """Fixed fan speed for a FireBoard Drive (Manual mode)."""

    _attr_icon = "mdi:fan"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        coordinator: FireBoardDataUpdateCoordinator,
        device_uuid: str,
    ) -> None:
        """Initialize the Drive fan speed control."""
        super().__init__(coordinator, device_uuid)
        self._attr_unique_id = f"{device_uuid}_drive_fan_control"
        self._attr_name = f"{self._device_title} Drive Manual Fan Speed"

    @property
    def native_value(self) -> float | None:
        """Return the current fan output percentage."""
        try:
            return round(float(self._drivelog.get("driveper")) * 100)
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Indicate whether the Drive is currently under manual control."""
        mode = drive_mode(self._drivelog)
        return {"manual_mode": mode == DRIVE_MODE_MANUAL} if mode else {}

    async def async_set_native_value(self, value: float) -> None:
        """Switch the Drive to Manual at the given fan speed."""
        await self.coordinator.async_send_drive_command(
            self._device_uuid,
            lambda: self.coordinator.client.set_drive_fan_speed(
                self._device_uuid, value
            ),
            {"driveper": value / 100, "modetype": 1},
        )
