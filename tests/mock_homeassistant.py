"""Mock Home Assistant modules for CI testing."""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Dict
from unittest.mock import MagicMock


class FlowResultType(Enum):
    """Mock FlowResultType enum."""

    FORM = "form"
    CREATE_ENTRY = "create_entry"
    ABORT = "abort"
    MENU = "menu"


class FlowResult:
    """Mock FlowResult class."""

    def __init__(self, flow_id: str, type: FlowResultType, data: dict = None):
        self.flow_id = flow_id
        self.type = type
        self.data = data or {}

    def __getitem__(self, key):
        """Make FlowResult subscriptable like a dictionary."""
        if key == "type":
            return self.type
        elif key == "data":
            if self.type == FlowResultType.CREATE_ENTRY:
                data_without_title = self.data.copy()
                data_without_title.pop("title", None)
                return data_without_title
            return self.data
        elif key == "flow_id":
            return self.flow_id
        elif key == "step_id":
            return self.data.get("step_id")
        elif key == "errors":
            return self.data.get("errors")
        elif key == "title":
            return self.data.get("title")
        else:
            return self.data.get(key)

    def get(self, key, default=None):
        """Support dict.get() method."""
        try:
            return self[key]
        except (KeyError, TypeError):
            return default

    def __contains__(self, key):
        """Support 'key in result' checks."""
        if key in ("type", "data", "flow_id"):
            return True
        return key in self.data


class HomeAssistant:
    """Mock HomeAssistant class."""

    def __init__(self, config_dir: str = ""):
        self.config_dir = config_dir
        self.data: Dict[str, Any] = {}
        self.config_entries = MagicMock()
        self.entity_registry = MagicMock()
        self.device_registry = MagicMock()

    async def async_start(self):
        """Mock async_start."""
        pass

    async def async_stop(self):
        """Mock async_stop."""
        pass

    async def async_add_executor_job(self, func, *args):
        """Mock async_add_executor_job: run synchronously in-line."""
        return func(*args)


class ConfigEntry:
    """Mock ConfigEntry class."""

    def __init__(self, **kwargs):
        self.entry_id = kwargs.get("entry_id", "test_entry_id")
        self.data = kwargs.get("data", {})
        self.options = kwargs.get("options", {})
        self.title = kwargs.get("title", "Test Entry")
        self.domain = kwargs.get("domain", "fireboard")
        self.source = kwargs.get("source", "user")
        self.version = kwargs.get("version", 1)
        self.minor_version = kwargs.get("minor_version", 1)
        self.unique_id = kwargs.get("unique_id")

    def add_to_hass(self, hass):
        """Mock add_to_hass method."""
        pass

    def add_update_listener(self, listener):
        """Mock add_update_listener; returns an unsubscribe callable."""
        self.update_listeners = getattr(self, "update_listeners", [])
        self.update_listeners.append(listener)
        return lambda: None

    def async_on_unload(self, func):
        """Mock async_on_unload."""
        self.on_unload = getattr(self, "on_unload", [])
        self.on_unload.append(func)


# Alias matching pytest-homeassistant-custom-component's MockConfigEntry,
# which the real test suite would otherwise provide.
MockConfigEntry = ConfigEntry


class AbortFlow(Exception):
    """Mock AbortFlow exception, mirroring data_entry_flow.AbortFlow."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class ConfigFlow:
    """Mock ConfigFlow class."""

    _flow_classes: Dict[str, type] = {}

    def __init__(self, *args, **kwargs):
        self.hass = None
        self.context: dict = {}
        self.unique_id: str | None = None

    def __init_subclass__(cls, domain=None, **kwargs):
        """Mock __init_subclass__ to handle domain parameter."""
        cls.domain = domain
        if domain:
            ConfigFlow._flow_classes[domain] = cls
        super().__init_subclass__(**kwargs)

    async def async_set_unique_id(self, unique_id):
        """Mock async_set_unique_id method."""
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        """Mock _abort_if_unique_id_configured method."""
        if self.unique_id is None or self.hass is None:
            return
        for entry in self.hass.config_entries.async_entries(self.domain):
            if entry.unique_id == self.unique_id:
                raise AbortFlow("already_configured")

    def async_show_form(self, step_id, data_schema=None, errors=None):
        """Mock async_show_form method."""
        data = {"step_id": step_id, "data_schema": data_schema}
        if errors:
            data["errors"] = errors
        return FlowResult("test_flow", FlowResultType.FORM, data)

    def _get_reconfigure_entry(self):
        """Mock _get_reconfigure_entry: the entry named in context."""
        return self.context["entry"]

    def _abort_if_unique_id_mismatch(self, reason="unique_id_mismatch"):
        """Mock _abort_if_unique_id_mismatch."""
        entry = self._get_reconfigure_entry()
        if entry.unique_id is not None and entry.unique_id != self.unique_id:
            raise AbortFlow(reason)

    def async_update_reload_and_abort(self, entry, data_updates=None):
        """Mock async_update_reload_and_abort."""
        entry.data = {**entry.data, **(data_updates or {})}
        return self.async_abort(reason="reconfigure_successful")

    def async_create_entry(self, title, data):
        """Mock async_create_entry method."""
        data_with_title = data.copy()
        data_with_title["title"] = title
        return FlowResult("test_flow", FlowResultType.CREATE_ENTRY, data_with_title)

    def async_abort(self, reason):
        """Mock async_abort method."""
        return FlowResult("test_flow", FlowResultType.ABORT, {"reason": reason})


class OptionsFlow:
    """Mock OptionsFlow class (config_entry is assigned by the caller)."""

    config_entry = None
    hass = None

    def async_show_form(
        self, step_id, data_schema=None, errors=None, description_placeholders=None
    ):
        """Mock async_show_form method."""
        data = {
            "step_id": step_id,
            "data_schema": data_schema,
            "description_placeholders": description_placeholders,
        }
        if errors:
            data["errors"] = errors
        return FlowResult("test_flow", FlowResultType.FORM, data)

    def async_show_menu(self, step_id, menu_options):
        """Mock async_show_menu method."""
        return FlowResult(
            "test_flow",
            FlowResultType.MENU,
            {"step_id": step_id, "menu_options": menu_options},
        )

    def async_abort(self, reason, description_placeholders=None):
        """Mock async_abort method."""
        return FlowResult(
            "test_flow",
            FlowResultType.ABORT,
            {"reason": reason, "description_placeholders": description_placeholders},
        )

    def async_create_entry(self, data, title=""):
        """Mock async_create_entry method."""
        return FlowResult("test_flow", FlowResultType.CREATE_ENTRY, dict(data))


def callback(func):
    """Mock homeassistant.core.callback decorator."""
    return func


class FlowManager:
    """Mock flow manager backing hass.config_entries.flow."""

    def __init__(self, hass: "HomeAssistant"):
        self._hass = hass

    async def async_init(self, domain, context=None, data=None):
        """Instantiate the registered ConfigFlow for domain and run the user step."""
        flow_class = ConfigFlow._flow_classes[domain]
        flow = flow_class()
        flow.hass = self._hass
        flow.context = context or {}
        try:
            return await flow.async_step_user(data)
        except AbortFlow as err:
            return flow.async_abort(err.reason)


class ConfigEntries:
    """Mock config entries manager backing hass.config_entries."""

    def __init__(self, hass: "HomeAssistant"):
        self._hass = hass
        self._entries: list[ConfigEntry] = []
        self.flow = FlowManager(hass)

    def async_entries(self, domain=None):
        """Mock async_entries method."""
        if domain is None:
            return list(self._entries)
        return [entry for entry in self._entries if entry.domain == domain]

    async def async_forward_entry_setups(self, entry, platforms):
        """Mock async_forward_entry_setups method."""

    async def async_unload_platforms(self, entry, platforms):
        """Mock async_unload_platforms method."""
        return True

    async def async_reload(self, entry_id):
        """Mock async_reload method."""
        self.reloaded = getattr(self, "reloaded", [])
        self.reloaded.append(entry_id)


SOURCE_USER = "user"


class DeviceInfo:
    """Mock DeviceInfo class."""

    def __init__(self, **kwargs):
        self.identifiers = kwargs.get("identifiers", set())
        self.manufacturer = kwargs.get("manufacturer", "")
        self.model = kwargs.get("model", "")
        self.name = kwargs.get("name", "")
        self.sw_version = kwargs.get("sw_version", "")


class DataUpdateCoordinator:
    """Mock DataUpdateCoordinator class.

    Mirrors the real refresh semantics subclasses rely on: _async_setup runs
    once, _async_update_data populates data, and UpdateFailed is swallowed
    into last_update_success rather than propagated (matching
    homeassistant.helpers.update_coordinator).
    """

    def __init__(self, hass: HomeAssistant, logger=None, **kwargs):
        self.hass = hass
        self.logger = logger
        self.data = None
        self.last_update_success = True
        self.last_exception: Exception | None = None
        self._setup_done = False
        self._listeners: list = []

    def async_add_listener(self, update_callback, context=None):
        """Mock async_add_listener; returns an unsubscribe callable."""
        self._listeners.append(update_callback)
        return lambda: self._listeners.remove(update_callback)

    def async_update_listeners(self):
        """Call every registered listener, like the real coordinator."""
        for listener in list(self._listeners):
            listener()

    async def _async_setup(self) -> None:
        """Overridden by subclasses; no-op by default."""

    async def _async_update_data(self):
        """Overridden by subclasses."""
        raise NotImplementedError

    async def _ensure_setup(self):
        if not self._setup_done:
            await self._async_setup()
            self._setup_done = True

    async def async_refresh(self):
        """Mock async_refresh, matching real HA: failures don't raise."""
        await self._ensure_setup()
        try:
            self.data = await self._async_update_data()
            self.last_update_success = True
            self.last_exception = None
            self.async_update_listeners()
        except UpdateFailed as err:
            self.last_exception = err
            self.last_update_success = False
        return self.data

    async def async_config_entry_first_refresh(self):
        """Mock async_config_entry_first_refresh."""
        await self.async_refresh()
        if not self.last_update_success:
            raise ConfigEntryNotReady from self.last_exception

    async def async_request_refresh(self):
        """Mock async_request_refresh."""
        await self.async_refresh()

    def async_set_updated_data(self, data):
        """Mock async_set_updated_data."""
        self.data = data
        self.last_update_success = True
        self.async_update_listeners()

    def __class_getitem__(cls, item):
        """Support generic type parameters."""
        return cls


class UpdateFailed(Exception):
    """Mock UpdateFailed exception."""

    pass


class ConfigEntryNotReady(Exception):
    """Mock ConfigEntryNotReady exception."""

    pass


class HomeAssistantError(Exception):
    """Mock HomeAssistantError exception."""

    pass


class BinarySensorEntity:
    """Mock BinarySensorEntity class."""

    pass


class SensorEntity:
    """Mock SensorEntity class."""

    @property
    def native_unit_of_measurement(self):
        """Return _attr_native_unit_of_measurement, mirroring real HA."""
        return getattr(self, "_attr_native_unit_of_measurement", None)


class CoordinatorEntity:
    """Mock CoordinatorEntity class."""

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self._attr_unique_id = None
        self._attr_name = None

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def name(self):
        return self._attr_name

    def __class_getitem__(cls, item):
        """Support generic type parameters, e.g. CoordinatorEntity[Foo]."""
        return cls


class Entity:
    """Mock Entity class."""

    pass


class NumberEntity:
    """Mock NumberEntity class."""

    @property
    def native_unit_of_measurement(self):
        """Return _attr_native_unit_of_measurement, mirroring real HA."""
        return getattr(self, "_attr_native_unit_of_measurement", None)


class NumberMode:
    """Mock NumberMode enum."""

    AUTO = "auto"
    BOX = "box"
    SLIDER = "slider"


class NumberDeviceClass:
    """Mock NumberDeviceClass enum."""

    TEMPERATURE = "temperature"


class ButtonEntity:
    """Mock ButtonEntity class."""

    pass


class MockSelectorModule:
    """Mock homeassistant.helpers.selector: every attribute is a passthrough."""

    def __getattr__(self, name):
        """Return a passthrough for any selector class or enum."""
        if name.endswith("Type") or name.endswith("Mode"):
            return MagicMock()
        return lambda *args, **kwargs: {"selector": name, "args": args, **kwargs}


# Mock constants
class Platform(Enum):
    """Mock Platform enum."""

    BINARY_SENSOR = "binary_sensor"
    BUTTON = "button"
    NUMBER = "number"
    SENSOR = "sensor"


class UnitOfTemperature:
    """Mock UnitOfTemperature enum."""

    FAHRENHEIT = "°F"
    CELSIUS = "°C"


class UnitOfElectricPotential:
    """Mock UnitOfElectricPotential enum."""

    VOLT = "V"


class BinarySensorDeviceClass:
    """Mock BinarySensorDeviceClass enum."""

    CONNECTIVITY = "connectivity"
    BATTERY = "battery"


class SensorDeviceClass:
    """Mock SensorDeviceClass enum."""

    TEMPERATURE = "temperature"
    BATTERY = "battery"
    VOLTAGE = "voltage"
    SIGNAL_STRENGTH = "signal_strength"


class SensorStateClass:
    """Mock SensorStateClass enum."""

    MEASUREMENT = "measurement"


class EntityCategory:
    """Mock EntityCategory enum."""

    CONFIG = "config"
    DIAGNOSTIC = "diagnostic"


# Mock configuration constants
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
PERCENTAGE = "%"
SIGNAL_STRENGTH_DECIBELS_MILLIWATT = "dBm"


class MockModule:
    """Mock module class."""

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class MockVoluptuous:
    """Mock voluptuous module."""

    def __getattr__(self, name):
        """Mock any voluptuous attribute."""
        return lambda *args, **kwargs: None


# Mock the homeassistant module structure
homeassistant = MockModule(
    core=MockModule(HomeAssistant=HomeAssistant, callback=callback),
    config_entries=MockModule(
        ConfigEntry=ConfigEntry,
        ConfigFlow=ConfigFlow,
        ConfigEntries=ConfigEntries,
        OptionsFlow=OptionsFlow,
        SOURCE_USER=SOURCE_USER,
    ),
    data_entry_flow=MockModule(
        FlowResultType=FlowResultType, FlowResult=FlowResult, AbortFlow=AbortFlow
    ),
    exceptions=MockModule(
        HomeAssistantError=HomeAssistantError,
        ConfigEntryNotReady=ConfigEntryNotReady,
    ),
    const=MockModule(
        Platform=Platform,
        UnitOfTemperature=UnitOfTemperature,
        UnitOfElectricPotential=UnitOfElectricPotential,
        CONF_EMAIL=CONF_EMAIL,
        CONF_PASSWORD=CONF_PASSWORD,
        PERCENTAGE=PERCENTAGE,
        SIGNAL_STRENGTH_DECIBELS_MILLIWATT=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        EntityCategory=EntityCategory,
    ),
    helpers=MockModule(
        entity=MockModule(
            DeviceInfo=DeviceInfo,
            Entity=Entity,
        ),
        device_registry=MockModule(
            DeviceInfo=DeviceInfo,
        ),
        entity_platform=MockModule(
            AddEntitiesCallback=Callable,
        ),
        update_coordinator=MockModule(
            DataUpdateCoordinator=DataUpdateCoordinator,
            UpdateFailed=UpdateFailed,
            CoordinatorEntity=CoordinatorEntity,
        ),
        selector=MockSelectorModule(),
        aiohttp_client=MockModule(
            async_get_clientsession=lambda hass: MagicMock(),
        ),
    ),
    components=MockModule(
        binary_sensor=MockModule(
            BinarySensorEntity=BinarySensorEntity,
            BinarySensorDeviceClass=BinarySensorDeviceClass,
        ),
        number=MockModule(
            NumberEntity=NumberEntity,
            NumberMode=NumberMode,
            NumberDeviceClass=NumberDeviceClass,
        ),
        button=MockModule(ButtonEntity=ButtonEntity),
        sensor=MockModule(
            SensorEntity=SensorEntity,
            SensorDeviceClass=SensorDeviceClass,
            SensorStateClass=SensorStateClass,
        ),
    ),
)

# Mock external dependencies
voluptuous = MockVoluptuous()
