"""Config flow for FireBoard integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api_client import (
    FireBoardApiClient,
    FireBoardApiClientAuthenticationError,
    FireBoardApiClientCommunicationError,
    FireBoardApiClientRateLimitError,
)
from .const import (
    CONF_BATTERY_LOW_THRESHOLD,
    CONF_DRIVE_CONTROLS,
    CONF_NOTIFY_BATTERY,
    CONF_NOTIFY_LID,
    CONF_NOTIFY_LIVE,
    CONF_NOTIFY_OFFLINE,
    CONF_NOTIFY_PROBE_ALERTS,
    CONF_NOTIFY_TARGETS,
    CONF_POLLING_INTERVAL,
    CONF_PROBE_ALERTS,
    DEFAULT_BATTERY_LOW_THRESHOLD,
    DEFAULT_DRIVE_CONTROLS,
    DEFAULT_POLLING_INTERVAL,
    DOMAIN,
    MAX_POLLING_INTERVAL,
    MIN_POLLING_INTERVAL,
    NOTIFY_TARGET_PERSISTENT,
    TEMPERATURE_MAX,
    TEMPERATURE_MIN,
)
from .notifications import FireBoardNotifier, probe_key

_LOGGER = logging.getLogger(__name__)

EMAIL_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(
        type=selector.TextSelectorType.EMAIL, autocomplete="username"
    )
)
PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(
        type=selector.TextSelectorType.PASSWORD, autocomplete="current-password"
    )
)
POLLING_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=MIN_POLLING_INTERVAL,
        max=MAX_POLLING_INTERVAL,
        step=5,
        unit_of_measurement="s",
        mode=selector.NumberSelectorMode.SLIDER,
    )
)
BATTERY_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=5,
        max=50,
        step=5,
        unit_of_measurement="%",
        mode=selector.NumberSelectorMode.SLIDER,
    )
)

# Notification switches and their defaults, in the order they're shown.
NOTIFICATION_TOGGLES: dict[str, bool] = {
    CONF_NOTIFY_PROBE_ALERTS: True,
    CONF_NOTIFY_LIVE: False,
    CONF_NOTIFY_LID: True,
    CONF_NOTIFY_OFFLINE: True,
    CONF_NOTIFY_BATTERY: True,
}

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): EMAIL_SELECTOR,
        vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
    }
)


def _credentials_schema(email: str) -> vol.Schema:
    """Build the credentials schema, pre-filled with the current email."""
    return vol.Schema(
        {
            vol.Required(CONF_EMAIL, default=email): EMAIL_SELECTOR,
            vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
        }
    )


def get_option(entry: config_entries.ConfigEntry, key: str, default: Any) -> Any:
    """Read a setting from options, falling back to entry data, then default.

    Entries created before the options flow existed stored polling_interval
    in entry data, so that's honored until the user saves options once.
    """
    if key in entry.options:
        return entry.options[key]
    return entry.data.get(key, default)


async def _validate_credentials(hass, email: str, password: str) -> dict[str, str]:
    """Try logging in; return a form errors dict (empty on success)."""
    try:
        client = FireBoardApiClient(
            email=email,
            password=password,
            session=async_get_clientsession(hass),
        )
        await client.authenticate()
        devices = await client.get_devices()
        _LOGGER.debug("Connected to FireBoard API, found %d devices", len(devices))
    except FireBoardApiClientAuthenticationError:
        return {"base": "invalid_auth"}
    except FireBoardApiClientRateLimitError:
        return {"base": "rate_limit"}
    except FireBoardApiClientCommunicationError:
        return {"base": "cannot_connect"}
    except Exception:  # pylint: disable=broad-except
        _LOGGER.exception("Unexpected error during connection test")
        return {"base": "unknown"}
    return {}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for FireBoard."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> FireBoardOptionsFlow:
        """Return the options flow handler."""
        return FireBoardOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await _validate_credentials(
                self.hass, user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if not errors:
                # Use email as the unique ID to prevent duplicate accounts
                await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"FireBoard ({user_input[CONF_EMAIL]})",
                    data={
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Let the user change the account email/password in place."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = await _validate_credentials(
                self.hass, user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
            )
            if not errors:
                await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_credentials_schema(entry.data.get(CONF_EMAIL, "")),
            errors=errors,
        )


class FireBoardOptionsFlow(config_entries.OptionsFlow):
    """Settings for an existing FireBoard account (Configure button).

    Opens a menu so each topic gets its own short, focused page.
    """

    def __init__(self) -> None:
        """Initialize the options flow."""
        self._probe_fields: dict[str, tuple[str, str]] = {}

    def _save(self, updates: dict[str, Any]) -> FlowResult:
        """Merge one page's values into the options, keeping the others."""
        options = dict(self.config_entry.options or {})
        return self.async_create_entry(data={**options, **updates})

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show the settings menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "general",
                "notifications",
                "probe_alerts",
                "test_notification",
            ],
        )

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit polling, battery threshold and Drive control."""
        if user_input is not None:
            return self._save(
                {
                    CONF_POLLING_INTERVAL: int(user_input[CONF_POLLING_INTERVAL]),
                    CONF_BATTERY_LOW_THRESHOLD: int(
                        user_input[CONF_BATTERY_LOW_THRESHOLD]
                    ),
                    CONF_DRIVE_CONTROLS: bool(user_input[CONF_DRIVE_CONTROLS]),
                }
            )

        entry = self.config_entry
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_POLLING_INTERVAL,
                    default=get_option(
                        entry, CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL
                    ),
                ): POLLING_SELECTOR,
                vol.Required(
                    CONF_BATTERY_LOW_THRESHOLD,
                    default=get_option(
                        entry, CONF_BATTERY_LOW_THRESHOLD, DEFAULT_BATTERY_LOW_THRESHOLD
                    ),
                ): BATTERY_SELECTOR,
                vol.Required(
                    CONF_DRIVE_CONTROLS,
                    default=get_option(
                        entry, CONF_DRIVE_CONTROLS, DEFAULT_DRIVE_CONTROLS
                    ),
                ): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="general", data_schema=schema)

    def _notify_target_options(self) -> list[dict[str, str]]:
        """List the places notifications can go, phones first."""
        options = []
        services = self.hass.services.async_services().get("notify", {})
        for service in sorted(services):
            if service in ("notify", "send_message", NOTIFY_TARGET_PERSISTENT):
                continue
            if service.startswith("mobile_app_"):
                name = service.removeprefix("mobile_app_").replace("_", " ").title()
                label = f"Mobile app: {name}"
            else:
                label = service.replace("_", " ").capitalize()
            options.append({"value": service, "label": label})
        options.append(
            {
                "value": NOTIFY_TARGET_PERSISTENT,
                "label": "Home Assistant persistent notifications",
            }
        )
        return options

    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose where notifications go and which ones to send."""
        if user_input is not None:
            return self._save(
                {
                    CONF_NOTIFY_TARGETS: list(
                        user_input.get(CONF_NOTIFY_TARGETS) or []
                    ),
                    **{key: bool(user_input.get(key)) for key in NOTIFICATION_TOGGLES},
                }
            )

        options = self.config_entry.options or {}
        available = self._notify_target_options()
        valid = {opt["value"] for opt in available}
        fields: dict[Any, Any] = {
            vol.Optional(
                CONF_NOTIFY_TARGETS,
                default=[t for t in options.get(CONF_NOTIFY_TARGETS, []) if t in valid],
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=available,
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
        }
        for key, default in NOTIFICATION_TOGGLES.items():
            fields[vol.Required(key, default=options.get(key, default))] = (
                selector.BooleanSelector()
            )

        return self.async_show_form(
            step_id="notifications",
            data_schema=vol.Schema(fields),
            description_placeholders={
                "phone_hint": (
                    ""
                    if len(available) > 1
                    else "\n\nNo mobile devices were found. Install the Home "
                    "Assistant Companion app to receive push notifications."
                )
            },
        )

    async def async_step_test_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Send a test notification and report where it went."""
        notifier = FireBoardNotifier(self.hass, self.config_entry, None)
        if not notifier.targets:
            return self.async_abort(reason="no_targets")

        labels = {opt["value"]: opt["label"] for opt in self._notify_target_options()}
        delivered, failed = await notifier.async_send_test()

        def _names(targets: list[str]) -> str:
            return ", ".join(labels.get(t, t) for t in targets)

        if failed:
            return self.async_abort(
                reason="test_failed",
                description_placeholders={
                    "delivered": _names(delivered) or "none",
                    "failed": _names(failed),
                },
            )
        return self.async_abort(
            reason="test_sent",
            description_placeholders={"delivered": _names(delivered)},
        )

    async def async_step_probe_alerts(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Per-probe target and minimum temperatures."""
        errors: dict[str, str] = {}
        if user_input is not None:
            alerts: dict[str, dict[str, float]] = {}
            for field_name, (key, bound) in self._probe_fields.items():
                value = user_input.get(field_name)
                if value in (None, ""):
                    continue
                if not TEMPERATURE_MIN <= float(value) <= TEMPERATURE_MAX:
                    errors[field_name] = "temperature_out_of_range"
                    continue
                alerts.setdefault(key, {})[bound] = float(value)
            if not errors:
                return self._save({CONF_PROBE_ALERTS: alerts})

        coordinator = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        devices = (getattr(coordinator, "data", None) or {}) if coordinator else {}
        if not devices:
            return self.async_abort(reason="no_probes")

        stored = (self.config_entry.options or {}).get(CONF_PROBE_ALERTS) or {}
        multiple_devices = len(devices) > 1
        fields: dict[Any, Any] = {}
        self._probe_fields = {}

        for device_uuid, data in devices.items():
            device_info = data.get("device_info", {})
            unit = "°C" if device_info.get("degreetype") == 1 else "°F"
            temp_selector = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=TEMPERATURE_MIN,
                    max=TEMPERATURE_MAX,
                    step=1,
                    unit_of_measurement=unit,
                    mode=selector.NumberSelectorMode.BOX,
                )
            )
            for channel in device_info.get("channels", []):
                number = channel.get("channel")
                if number is None:
                    continue
                label = channel.get("channel_label") or f"Probe {number}"
                if multiple_devices:
                    label = f"{device_info.get('title', 'FireBoard')} · {label}"
                key = probe_key(device_uuid, number)
                for bound, suffix in (("max", "target"), ("min", "minimum")):
                    field_name = f"{label} – {suffix}"
                    self._probe_fields[field_name] = (key, bound)
                    current = (
                        user_input.get(field_name)
                        if user_input is not None
                        else stored.get(key, {}).get(bound)
                    )
                    fields[
                        vol.Optional(
                            field_name,
                            description={"suggested_value": current},
                        )
                    ] = temp_selector

        return self.async_show_form(
            step_id="probe_alerts", data_schema=vol.Schema(fields), errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class RateLimitExceeded(HomeAssistantError):
    """Error to indicate rate limit was exceeded."""
