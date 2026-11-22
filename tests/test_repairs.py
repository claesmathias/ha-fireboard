"""Tests for the Repairs warning shown when FireBoard Cloud is unreachable."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.fireboard.api_client import (
    FireBoardApiClient,
    FireBoardApiClientAuthenticationError,
    FireBoardApiClientCommunicationError,
)
from custom_components.fireboard.const import DOMAIN
from custom_components.fireboard.coordinator import FireBoardDataUpdateCoordinator

ENTRY_ID = "entry1"
ISSUE = (DOMAIN, f"cloud_unreachable_{ENTRY_ID}")


@pytest.fixture
def coordinator(hass):
    """Return a coordinator whose data fetch can be scripted per test."""
    entry = ConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        title="FireBoard (me@example.com)",
        data={"email": "me@example.com", "password": "pw"},
    )
    coord = FireBoardDataUpdateCoordinator(hass, entry)
    coord._async_fetch_data = AsyncMock(return_value={})
    return coord


def _issues(hass):
    return getattr(hass, "_mock_issues", {})


def _communication_failure():
    err = UpdateFailed("Communication error")
    err.__cause__ = FireBoardApiClientCommunicationError("timeout")
    return err


async def test_warning_after_three_failures_and_cleared_on_success(hass, coordinator):
    """Three failed updates in a row raise the warning; success removes it."""
    coordinator._async_fetch_data.side_effect = _communication_failure()
    for _ in range(2):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
    assert _issues(hass) == {}

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    issue = _issues(hass)[ISSUE]
    assert issue["translation_key"] == "cloud_unreachable"
    assert issue["severity"] == "warning"
    assert issue["is_fixable"] is False
    assert issue["translation_placeholders"] == {
        "account": "FireBoard (me@example.com)",
        "error": "timeout",
    }

    coordinator._async_fetch_data.side_effect = None
    await coordinator._async_update_data()
    assert _issues(hass) == {}
    assert coordinator.consecutive_failures == 0
    assert coordinator.last_error is None


async def test_rejected_credentials_also_warn(hass, coordinator):
    """A rejected login is a lost connection too, with the reason shown."""
    coordinator._async_fetch_data.side_effect = FireBoardApiClientAuthenticationError(
        "Invalid email or password"
    )
    for _ in range(3):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
    placeholders = _issues(hass)[ISSUE]["translation_placeholders"]
    assert placeholders["error"] == "Invalid email or password"


async def test_auth_error_passes_through_fetch(hass, mock_config_entry_data):
    """The fetch doesn't wrap auth errors as 'unexpected' errors."""
    entry = ConfigEntry(domain=DOMAIN, data=mock_config_entry_data)
    coord = FireBoardDataUpdateCoordinator(hass, entry)
    coord.client = AsyncMock()
    coord.client.auth_token = "tok"
    coord.client.get_devices.side_effect = FireBoardApiClientAuthenticationError("x")
    with pytest.raises(FireBoardApiClientAuthenticationError):
        await coord._async_fetch_data()


async def test_login_400_is_invalid_credentials():
    """Treat HTTP 400 from login as a wrong password (FireBoard's answer)."""
    session = MagicMock()
    session.post = AsyncMock(return_value=MagicMock(status=400))
    client = FireBoardApiClient("me@example.com", "wrong", session)
    with pytest.raises(FireBoardApiClientAuthenticationError):
        await client.authenticate()


async def test_remove_entry_deletes_its_warning(hass):
    """Deleting the account removes its warning, not other accounts'."""
    from homeassistant.helpers import issue_registry as ir

    from custom_components.fireboard import async_remove_entry

    ir.async_create_issue(hass, DOMAIN, f"cloud_unreachable_{ENTRY_ID}")
    ir.async_create_issue(hass, DOMAIN, "cloud_unreachable_other")
    await async_remove_entry(hass, ConfigEntry(domain=DOMAIN, entry_id=ENTRY_ID))
    assert list(_issues(hass)) == [(DOMAIN, "cloud_unreachable_other")]
