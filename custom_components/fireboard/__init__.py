"""The FireBoard integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import FireBoardDataUpdateCoordinator
from .notifications import FireBoardNotifier

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.BUTTON,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up FireBoard from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Create coordinator
    coordinator = FireBoardDataUpdateCoordinator(hass, entry)

    # Fetch initial data. DataUpdateCoordinator runs _async_setup()
    # (authentication + MQTT) as part of the first refresh, so it must not
    # also be called here -- doing so logged in and connected MQTT twice.
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Built-in notifications (Configure > Notifications).
    notifier = FireBoardNotifier(hass, entry, coordinator)
    entry.async_on_unload(coordinator.async_add_listener(notifier.async_handle_update))

    # Apply changes from the Configure (options) dialog by reloading.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Shutdown MQTT connection
    coordinator: FireBoardDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_shutdown()

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Remove data
    if unload_ok and entry.entry_id in hass.data[DOMAIN]:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
