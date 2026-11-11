"""Base entity for FireBoard integration."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import FireBoardDataUpdateCoordinator


class FireBoardEntity(CoordinatorEntity[FireBoardDataUpdateCoordinator]):
    """Base entity for FireBoard devices."""

    def __init__(
        self,
        coordinator: FireBoardDataUpdateCoordinator,
        device_uuid: str,
        channel_number: int | None = None,
    ) -> None:
        """Initialize the entity.

        Args:
            coordinator: Data update coordinator
            device_uuid: Device UUID
            channel_number: Optional channel number for temperature entities

        """
        super().__init__(coordinator)
        self._device_uuid = device_uuid
        self._channel_number = channel_number

        # Get device info from coordinator data
        device_data = self.coordinator.data.get(device_uuid, {})
        device_info = device_data.get("device_info", {})

        self._device_title = device_info.get("title", "FireBoard")
        # "model_name" is the marketing name (e.g. "FireBoard 2 Pro");
        # "hardware_id" is the board's serial, used only as a fallback.
        self._device_model = (
            device_info.get("model_name") or device_info.get("hardware_id") or "Unknown"
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        device_data = self.coordinator.data.get(self._device_uuid, {})
        device_info = device_data.get("device_info", {})

        return DeviceInfo(
            identifiers={(DOMAIN, self._device_uuid)},
            name=self._device_title,
            manufacturer="FireBoard",
            model=self._device_model,
            model_id=device_info.get("model"),
            serial_number=device_info.get("hardware_id"),
            # devices.json has no "software_version" field; "version" is the
            # closest match (device firmware/image version, e.g. "4.2.30").
            sw_version=device_info.get("version"),
            configuration_url="https://fireboard.io",
        )

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        # Entity is available if coordinator has recent data
        # and the device is marked as online
        if not self.coordinator.last_update_success:
            return False

        device_data = self.coordinator.data.get(self._device_uuid, {})
        return device_data.get("online", False)

    @property
    def _device_data(self) -> dict[str, Any]:
        """Return device data from coordinator."""
        return self.coordinator.data.get(self._device_uuid, {})

    @property
    def _temperatures(self) -> dict[str, Any]:
        """Return temperature data for this device."""
        return self._device_data.get("temperatures", {})


def device_has_drive(device_data: dict[str, Any]) -> bool:
    """Return whether a FireBoard Drive has been seen on this device."""
    return bool(
        device_data.get("has_drive")
        or device_data.get("device_info", {}).get("last_drivelog")
    )


def async_add_drive_entities(
    coordinator: FireBoardDataUpdateCoordinator,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    factory: Callable[[str], Iterable[Entity]],
) -> None:
    """Add Drive entities now, and later for any Drive that shows up.

    A Drive is often only detected after setup (it reports only while
    plugged in and running), so listen for coordinator updates instead of
    requiring a reload.
    """
    added: set[str] = set()

    @callback
    def _add_new_drives() -> None:
        new_entities: list[Entity] = []
        for device_uuid, device_data in (coordinator.data or {}).items():
            if device_uuid not in added and device_has_drive(device_data):
                added.add(device_uuid)
                new_entities.extend(factory(device_uuid))
        if new_entities:
            async_add_entities(new_entities)

    _add_new_drives()
    config_entry.async_on_unload(coordinator.async_add_listener(_add_new_drives))
