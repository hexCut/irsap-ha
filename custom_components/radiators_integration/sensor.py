import requests
import logging
import json
from homeassistant.components.sensor import SensorEntity
from warrant import Cognito

_LOGGER = logging.getLogger(__name__)

# Configuration for your User Pool ID, Client ID, and region
USER_POOL_ID = "eu-west-1_qU4ok6EGG"  # Replace with your User Pool ID
CLIENT_ID = "4eg8veup8n831ebokk4ii5uasf"  # Replace with your Client ID
REGION = "eu-west-1"  # Replace with your region


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
        # Obtain envID
        envID = envid_with_srp(username, password, token)
        if envID:
            _LOGGER.debug("envID successfully obtained. Fetching radiators.")

            radiators = get_radiators(token, envID)
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
            _LOGGER.error("Unable to get the envID. Check credentials.")
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


def envid_with_srp(username, password, token):
    """Login and obtain the envID using Warrant."""
    url = (
        "https://flqpp5xzjzacpfpgkloiiuqizq.appsync-api.eu-west-1.amazonaws.com/graphql"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    graphql_query = {
        "operationName": "ListEnvironments",
        "variables": {},
        "query": "query ListEnvironments {\n listEnvironments {\n environments {\n envId\n envName\n userRole\n __typename\n }\n __typename\n }\n}\n",
    }

    try:
        response = requests.post(url, headers=headers, json=graphql_query)
        if response.status_code == 200:
            data = response.json()
            envId = data["data"]["listEnvironments"]["environments"][0]["envId"]
            _LOGGER.debug(f"envId retrieved from API: {envId}")
            return envId
        else:
            _LOGGER.error(f"API request error: {response.status_code}")
            return []
    except Exception as e:
        _LOGGER.error(f"Error during API call: {e}")
        return []


def get_radiators(token, envID):
    """Fetch radiator data from the API."""
    url = (
        "https://flqpp5xzjzacpfpgkloiiuqizq.appsync-api.eu-west-1.amazonaws.com/graphql"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    graphql_query = {
        "operationName": "GetShadow",
        "variables": {"envId": envID},
        "query": "query GetShadow($envId: ID!) {\n  getShadow(envId: $envId) {\n    envId\n    payload\n    __typename\n  }\n}\n",
    }

    try:
        response = requests.post(url, headers=headers, json=graphql_query)
        if response.status_code == 200:
            data = response.json()
            payload = json.loads(data["data"]["getShadow"]["payload"])
            _LOGGER.debug(f"Payload retrieved from API: {payload}")

            return extract_device_info(payload["state"]["desired"])
        else:
            _LOGGER.error(f"API request error: {response.status_code}")
            return []
    except ValueError as e:
        _LOGGER.error(f"Error converting temperature: {e}")
        return []
    except Exception as e:
        _LOGGER.error(f"Error during API call: {e}")
        return []


def extract_device_info(
    payload, nam_suffix="_NAM", tmp_suffix="_TMP", exclude_suffix="E_NAM"
):
    devices_info = []

    # Funzione ricorsiva per cercare chiavi che terminano con _NAM e _TMP
    def find_device_keys(obj):
        if isinstance(obj, dict):  # Se l'oggetto è un dizionario
            for key, value in obj.items():
                # Verifica se la chiave termina con _NAM e non è una chiave esclusa
                if key.endswith(nam_suffix) and not key.startswith(exclude_suffix):
                    # Aggiunge un dizionario con il suo serial
                    device_info = {
                        "serial": value,  # Usa il valore della chiave _NAM come serial
                        "temperature": 0,  # Default a 0 se non trovata
                    }
                    # Trova il corrispondente _TMP
                    corresponding_tmp_key = key[: -len(nam_suffix)] + tmp_suffix
                    if corresponding_tmp_key in obj:
                        # Assegna la temperatura se esiste e non è None
                        tmp_value = obj[corresponding_tmp_key]
                        device_info["temperature"] = (
                            float(tmp_value) / 10 if tmp_value is not None else 0
                        )

                    devices_info.append(
                        device_info
                    )  # Aggiunge l'informazione del dispositivo
                # Ricorsione su sotto-dizionari
                find_device_keys(value)
        elif isinstance(obj, list):  # Se l'oggetto è una lista
            for item in obj:
                find_device_keys(item)  # Ricorsione sugli elementi della lista

    # Inizio della ricerca nel payload
    find_device_keys(payload)
    return devices_info


class RadiatorTemperatureSensor(SensorEntity):
    """Sensor for radiator temperature."""

    def __init__(self, radiator, token):
        self._radiator = radiator
        self._token = token
        self._state = None
        self._name = f"{radiator['serial']}"
        self._unique_id = f"radiator_{radiator['serial']}"

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
        self._state = float(
            self._radiator["temperature"]
        )  # Ensure it's treated as a number
