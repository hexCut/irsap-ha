import requests
import logging
import json
from homeassistant.components.switch import SwitchEntity
from warrant import Cognito

_LOGGER = logging.getLogger(__name__)

# Configuration for your User Pool ID, Client ID, and region
USER_POOL_ID = "eu-west-1_qU4ok6EGG"
CLIENT_ID = "4eg8veup8n831ebokk4ii5uasf"
REGION = "eu-west-1"


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Setup the switch platform."""
    _LOGGER.debug("Starting switch platform setup.")

    username = config.get("username")
    password = config.get("password")

    _LOGGER.debug(f"Username: {username}, Password: {password}")

    # Login to obtain the token
    token = login_with_srp(username, password)
    if token:
        _LOGGER.debug("Token successfully obtained. Retrieving radiators.")

        # Obtain envID
        envID = envid_with_srp(username, password, token)
        if envID:
            _LOGGER.debug("envID successfully obtained. Fetching radiators.")

            radiators = get_radiators(token, envID)
        if radiators:
            switches = []
            for radiator in radiators:
                _LOGGER.debug(f"Adding switch for radiator: {radiator['serial']}")
                switches.append(RadiatorSwitch(radiator, token, envID))
            add_entities(switches, True)
            _LOGGER.debug(f"Created {len(switches)} switches.")
        else:
            _LOGGER.warning("No radiators found in the API.")
    else:
        _LOGGER.error("Unable to obtain the token. Check credentials.")


def login_with_srp(username, password):
    """Log in and obtain the access token using Warrant."""
    try:
        u = Cognito(USER_POOL_ID, CLIENT_ID, username=username, user_pool_region=REGION)
        u.authenticate(password=password)
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
    """Retrieve radiator data from the API."""
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
    except Exception as e:
        _LOGGER.error(f"Error during API call: {e}")
        return []


def extract_device_info(
    payload,
    nam_suffix="_NAM",
    srl_suffix="_SRL",
    enb_suffix="_ENB",
    exclude_suffix="E_NAM",
):
    devices_info = []

    # Funzione ricorsiva per cercare chiavi che terminano con _NAM, _SRL e _ENB
    def find_device_keys(obj):
        if isinstance(obj, dict):  # Se l'oggetto è un dizionario
            for key, value in obj.items():
                # Ignora le chiavi che iniziano con E_NAM
                if key.startswith(exclude_suffix):
                    continue

                # Verifica se la chiave termina con _NAM e che non sia vuoto
                if key.endswith(nam_suffix) and value:
                    device_info = {
                        "serial": None,  # Default a None
                        "is_on": False,  # Default a False
                        "name": value,  # Usa il valore di _NAM come nome
                    }

                    # Cerca il corrispondente _SRL
                    corresponding_srl_key = key[: -len(nam_suffix)] + srl_suffix
                    if corresponding_srl_key in obj and obj[corresponding_srl_key]:
                        device_info["serial"] = obj[
                            corresponding_srl_key
                        ]  # Assegna il valore di _SRL

                    # Cerca il corrispondente _ENB
                    corresponding_enb_key = key[: -len(nam_suffix)] + enb_suffix
                    if corresponding_enb_key in obj:
                        enb_value = obj[corresponding_enb_key]
                        if enb_value:  # Se _ENB non è vuoto, usa il suo valore
                            device_info["is_on"] = True if enb_value == "1" else False
                        else:
                            device_info["is_on"] = (
                                False  # Se _ENB è vuoto, assegna False
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


class RadiatorSwitch(SwitchEntity):
    """Switch to turn radiators on/off."""

    def __init__(self, radiator, token, envID):
        self._radiator = radiator
        self._token = token
        self._state = radiator["is_on"]
        self._name = f"{radiator['name']}"
        self._envID = envID

    @property
    def name(self):
        """Return the name of the switch."""
        return self._name

    @property
    def is_on(self):
        """Return the state of the switch."""
        return self._state

    def turn_on(self, **kwargs):
        """Turn on the radiator."""
        _LOGGER.debug(f"Turn on called for radiator {self._radiator['serial']}")
        self._set_radiator_state(True)

    def turn_off(self, **kwargs):
        """Turn off the radiator."""
        _LOGGER.debug(f"Turn off called for radiator {self._radiator['serial']}")
        self._set_radiator_state(False)

    def _set_radiator_state(self, state):
        """Send request to set the radiator state."""
        _LOGGER.debug(
            f"Setting radiator state: {self._radiator['serial']} to {'on' if state else 'off'}"
        )

        url = "https://flqpp5xzjzacpfpgkloiiuqizq.appsync-api.eu-west-1.amazonaws.com/graphql"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

        # Update the Pca_ENB field to control the radiator
        payload = {
            "operationName": "UpdateShadow",
            "variables": {
                "envId": self._envID,
                "payload": json.dumps(
                    {
                        "state": {
                            "desired": {
                                "PCM_ENB": 1
                                if state
                                else 0  # Turns the radiator on/off
                            }
                        }
                    }
                ),
            },
            "query": "mutation UpdateShadow($envId: ID!, $payload: AWSJSON!) {\n  asyncUpdateShadow(envId: $envId, payload: $payload) {\n    status\n    code\n    message\n    payload\n    __typename\n  }\n}\n",
        }

        _LOGGER.debug(f"Payload sent: {payload}")

        try:
            response = requests.post(url, headers=headers, json=payload)
            _LOGGER.debug(f"API response: {response.status_code}, {response.text}")
            if response.status_code == 200:
                _LOGGER.debug(
                    f"Radiator state {self._radiator['serial']} updated successfully."
                )
                self._state = state
            else:
                _LOGGER.error(
                    f"Error updating radiator state {self._radiator['serial']}: {response.status_code}"
                )
        except Exception as e:
            _LOGGER.error(
                f"Error setting radiator state {self._radiator['serial']}: {e}"
            )

    def update(self):
        """Update the switch state by querying the API."""
        _LOGGER.debug(f"Updating radiator state {self._radiator['serial']}")

        url = "https://flqpp5xzjzacpfpgkloiiuqizq.appsync-api.eu-west-1.amazonaws.com/graphql"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

        graphql_query = {
            "operationName": "GetShadow",
            "variables": {"envId": self._envID},  # Replace with the correct envId
            "query": "query GetShadow($envId: ID!) {\n  getShadow(envId: $envId) {\n    envId\n    payload\n    __typename\n  }\n}\n",
        }

        try:
            response = requests.post(url, headers=headers, json=graphql_query)
            if response.status_code == 200:
                data = response.json()
                payload = json.loads(data["data"]["getShadow"]["payload"])
                _LOGGER.debug(f"Payload updated from API: {payload}")

                # Update the switch state with the current value
                self._state = payload["state"]["desired"]["PCM_ENB"]
            else:
                _LOGGER.error(
                    f"API request error during state update: {response.status_code}"
                )
        except Exception as e:
            _LOGGER.error(f"Error updating radiator state: {e}")
