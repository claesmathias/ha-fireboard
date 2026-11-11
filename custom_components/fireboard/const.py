"""Constants for the FireBoard integration."""

from typing import Final

# Integration domain
DOMAIN: Final = "fireboard"

# API Configuration
API_BASE_URL: Final = "https://fireboard.io/api/v1"
API_TIMEOUT: Final = 30

# Per https://docs.fireboard.io/app/app-api/: max 17 calls per 5-minute window
API_RATE_LIMIT_MAX_CALLS: Final = 17
API_RATE_LIMIT_WINDOW_SECONDS: Final = 300

# Configuration keys
CONF_EMAIL: Final = "email"
CONF_PASSWORD: Final = "password"
CONF_POLLING_INTERVAL: Final = "polling_interval"
CONF_BATTERY_LOW_THRESHOLD: Final = "battery_low_threshold"
CONF_DRIVE_CONTROLS: Final = "drive_controls"

# Notification settings (Configure > Notifications / Probe alerts)
CONF_NOTIFY_TARGETS: Final = "notify_targets"
CONF_NOTIFY_PROBE_ALERTS: Final = "notify_probe_alerts"
CONF_NOTIFY_LIVE: Final = "notify_live"
CONF_NOTIFY_LID: Final = "notify_lid"
CONF_NOTIFY_OFFLINE: Final = "notify_offline"
CONF_NOTIFY_BATTERY: Final = "notify_battery"
CONF_PROBE_ALERTS: Final = "probe_alerts"
# Pseudo notify target: Home Assistant's own sidebar notifications.
NOTIFY_TARGET_PERSISTENT: Final = "persistent_notification"

# Default values
DEFAULT_POLLING_INTERVAL: Final = 40  # seconds (90 calls/hour, well under 200 limit)
MIN_POLLING_INTERVAL: Final = 40  # minimum to respect rate limits
MAX_POLLING_INTERVAL: Final = 300  # 5 minutes maximum
DEFAULT_BATTERY_LOW_THRESHOLD: Final = 20  # percent

# Temperature limits, matching the FireBoard Android app (v4.5.2): its alert
# fields only accept unsigned numbers (inputType="numberDecimal"), and it
# clamps the Drive setpoint to 0-1000. Values are in the account's unit.
TEMPERATURE_MIN: Final = 0
TEMPERATURE_MAX: Final = 1000
DEFAULT_DRIVE_CONTROLS: Final = True

# Device information
ATTR_DEVICE_ID: Final = "device_id"
ATTR_DEVICE_UUID: Final = "uuid"
ATTR_DEVICE_TITLE: Final = "title"
ATTR_DEVICE_MODEL: Final = "model"
ATTR_DEVICE_HARDWARE: Final = "hardware_id"

# Channel information
ATTR_CHANNEL_NUMBER: Final = "channel"
ATTR_CHANNEL_LABEL: Final = "label"
ATTR_TEMPERATURE: Final = "temperature"
ATTR_TARGET_TEMP: Final = "target_temp"

# Session information
ATTR_SESSION_ID: Final = "session_id"
ATTR_SESSION_START: Final = "start_time"

# Battery information
ATTR_BATTERY_LEVEL: Final = "battery_level"
ATTR_BATTERY_LOW: Final = "battery_low"

# Connection status
ATTR_ONLINE: Final = "online"
ATTR_LAST_SEEN: Final = "last_seen"
