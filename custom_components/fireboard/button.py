"""Button platform for FireBoard integration: FireBoard Drive off."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import FireBoardDataUpdateCoordinator
from .entity import FireBoardEntity, async_add_drive_entities
from .notifications import FireBoardNotifier
from .number import drive_controls_enabled


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FireBoard button entities."""
    coordinator: FireBoardDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]

    # One "send test notification" button per device, so notifications
    # can be checked from the device page or a dashboard.
    async_add_entities(
        FireBoardTestNotificationButton(coordinator, device_uuid, config_entry)
        for device_uuid in coordinator.data
    )

    if not drive_controls_enabled(config_entry):
        return

    async_add_drive_entities(
        coordinator,
        config_entry,
        async_add_entities,
        lambda device_uuid: [FireBoardDriveOffButton(coordinator, device_uuid)],
    )


class FireBoardDriveOffButton(FireBoardEntity, ButtonEntity):
    """Turn a FireBoard Drive's fan off."""

    _attr_icon = "mdi:fan-off"

    def __init__(
        self,
        coordinator: FireBoardDataUpdateCoordinator,
        device_uuid: str,
    ) -> None:
        """Initialize the Drive off button."""
        super().__init__(coordinator, device_uuid)
        self._attr_unique_id = f"{device_uuid}_drive_off"
        self._attr_name = f"{self._device_title} Drive Off"

    async def async_press(self) -> None:
        """Send the Drive off command."""
        await self.coordinator.async_send_drive_command(
            self._device_uuid,
            lambda: self.coordinator.client.turn_drive_off(self._device_uuid),
            {"setpoint": 0, "driveper": 0, "modetype": 0},
        )


class FireBoardTestNotificationButton(FireBoardEntity, ButtonEntity):
    """Send a test notification to the targets chosen in Configure."""

    _attr_icon = "mdi:bell-ring-outline"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FireBoardDataUpdateCoordinator,
        device_uuid: str,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the test notification button."""
        super().__init__(coordinator, device_uuid)
        self._config_entry = config_entry
        self._attr_unique_id = f"{device_uuid}_test_notification"
        self._attr_name = f"{self._device_title} Send Test Notification"

    @property
    def available(self) -> bool:
        """Work even while the FireBoard itself is switched off."""
        return True

    async def async_press(self) -> None:
        """Send the test notification."""
        notifier = FireBoardNotifier(self.hass, self._config_entry, None)
        if not notifier.targets:
            raise HomeAssistantError(
                "No notification targets set. Choose them under "
                "FireBoard > Configure > Notifications."
            )
        _, failed = await notifier.async_send_test()
        if failed:
            raise HomeAssistantError(
                f"Test notification failed for: {', '.join(failed)}"
            )
