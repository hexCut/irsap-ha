"""Constants for the irsap_ha integration."""

DOMAIN = "irsap_ha"

# Config Entry Keys
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

# Default values
DEFAULT_NAME = "Radiator"

# Cognito Configuration
USER_POOL_ID = "eu-west-1_qU4ok6EGG"
CLIENT_ID = "4eg8veup8n831ebokk4ii5uasf"
REGION = "eu-west-1"

# Polling
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 60  # seconds
MIN_SCAN_INTERVAL = 30  # seconds
MAX_SCAN_INTERVAL = 3600  # seconds

# Cognito access tokens are valid for 1 hour: reuse them instead of running a
# full SRP login on every update.
TOKEN_MAX_AGE = 50 * 60  # seconds

# Timeout for a single call to the IRSAP cloud API
API_TIMEOUT = 20  # seconds
