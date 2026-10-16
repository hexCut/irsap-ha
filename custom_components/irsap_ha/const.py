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

# Cognito SRP login: timeouts for each HTTP call made by boto3, and an upper
# bound on the whole login so a hanging call can't stall the coordinator.
COGNITO_CONNECT_TIMEOUT = 10  # seconds
COGNITO_READ_TIMEOUT = 10  # seconds
LOGIN_TIMEOUT = 30  # seconds

# After a command, ignore cloud updates for this long so a shadow that does not
# reflect the change yet cannot revert the new state in the UI.
WRITE_SETTLE_TIME = 15  # seconds
