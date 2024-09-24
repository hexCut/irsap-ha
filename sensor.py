import requests
import logging
import json
from homeassistant.components.sensor import SensorEntity
from warrant import Cognito

_LOGGER = logging.getLogger(__name__)

# Configuration for your User Pool ID, Client ID, and region
USER_POOL_ID = 'eu-west-1_qU4ok6EGG'  # Replace with your User Pool ID
CLIENT_ID = '4eg8veup8n831ebokk4ii5uasf'  # Replace with your Client ID
REGION = 'eu-west-1'  # Replace with your region

# Define radiators from YAML configuration
def setup_platform(hass, config, add_entities, discovery_info=None):
    """Setup the sensor platform."""
    username = config.get("username")
    password = config.get("password")

    _LOGGER.debug("Starting platform setup. Fetching token...")

    # Login to obtain the access token
    token = login_with_srp(username, password)
    if token:
        _LOGGER.debug("Token successfully obtained. Fetching radiators.")

        radiators = get_radiators(token)
        if radiators:
            sensors = []
            for radiator in radiators:
                _LOGGER.debug(f"Adding radiator: {radiator['serial']}")
                sensors.append(RadiatorTemperatureSensor(radiator, token))
            add_entities(sensors, True)
            _LOGGER.debug(f"Created {len(sensors)} sensors.")
        else:
            _LOGGER.warning("No radiators found in the API.")
    else:
        _LOGGER.error("Unable to get the token. Check credentials.")

def login_with_srp(username, password):
    """Login and obtain the access token using Warrant."""
    try:
        # Configure Cognito client with User Pool ID, Client ID, username, and region
        u = Cognito(USER_POOL_ID, CLIENT_ID, username=username, user_pool_region=REGION)

        # Authenticate using SRP
        u.authenticate(password=password)

        # Get access token
        _LOGGER.debug(f"Access Token: {u.access_token}")
        return u.access_token
    except Exception as e:
        _LOGGER.error(f"Error during login: {e}")
        return None

def get_radiators(token):
    """Fetch radiator data from the API."""
    url = 'https://flqpp5xzjzacpfpgkloiiuqizq.appsync-api.eu-west-1.amazonaws.com/graphql'
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    graphql_query = {
        "operationName": "GetShadow",
        "variables": {"envId": "5f742ece-5b53-41c2-8996-1d6793e6a7e9"},  # Replace with your generated envId
        "query": "query GetShadow($envId: ID!) {\n  getShadow(envId: $envId) {\n    envId\n    payload\n    __typename\n  }\n}\n"
    }

    try:
        response = requests.post(url, headers=headers, json=graphql_query)
        if response.status_code == 200:
            data = response.json()
            payload = json.loads(data['data']['getShadow']['payload'])
            _LOGGER.debug(f"Payload retrieved from API: {payload}")
            
            # Convert temperatures to float
            return [
                {
                    "serial": "Bagno Padronale",
                    "temperature": float(payload['state']['desired']['Pca_TMP']) / 10,
                },
                {
                    "serial": "Bagno Piano Primo",
                    "temperature": float(payload['state']['desired']['Pwg_TMP']) / 10,
                },
                {
                    "serial": "Bagno Piano Terra",
                    "temperature": float(payload['state']['desired']['PTG_TMP']) / 10,
                }
            ]
        else:
            _LOGGER.error(f"API request error: {response.status_code}")
            return []
    except ValueError as e:
        _LOGGER.error(f"Error converting temperature: {e}")
        return []
    except Exception as e:
        _LOGGER.error(f"Error during API call: {e}")
        return []

class RadiatorTemperatureSensor(SensorEntity):
    """Sensor for radiator temperature."""

    def __init__(self, radiator, token):
        self._radiator = radiator
        self._token = token
        self._state = None
        self._name = f"{radiator['serial']}_temp"
        self._unique_id = f"radiator_{radiator['serial']}_temp"

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unique_id(self):
        """Return a unique ID for the sensor."""
        return self._unique_id

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement for temperature."""
        return "°C"  # Ensures Home Assistant treats it as temperature

    @property
    def device_class(self):
        """Return the device class."""
        return "temperature"  # Indicates this is a temperature sensor

    def update(self):
        """Update the sensor value."""
        _LOGGER.debug(f"Updating radiator temperature {self._radiator['serial']}")
        self._state = float(self._radiator['temperature'])  # Ensure it's treated as a number
