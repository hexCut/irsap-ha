import logging
from homeassistant.components.climate import (
    ClimateEntity,
    HVACMode,  # Importa HVACMode
)
from homeassistant.components.climate.const import ClimateEntityFeature
from homeassistant.const import UnitOfTemperature  # Importa UnitOfTemperature
from .const import DOMAIN, USER_POOL_ID, CLIENT_ID, REGION
import aiohttp
import json
from warrant import Cognito

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up climate platform."""
    envID = config_entry.data["envID"]
    username = config_entry.data["username"]
    password = config_entry.data["password"]

    token = await hass.async_add_executor_job(login_with_srp, username, password)

    if token and envID:
        _LOGGER.debug("Token and envID successfully obtained. Retrieving radiators.")
        radiators = await get_radiators(token, envID)
        if radiators:
            entities = [
                RadiatorClimate(radiator, token, envID) for radiator in radiators
            ]
            async_add_entities(entities, True)  # Aggiungi le entità alla piattaforma
            _LOGGER.debug(f"Created {len(entities)} radiators.")
        else:
            _LOGGER.warning("No radiators found in the API.")
    else:
        _LOGGER.error("Unable to obtain the token or envID. Check configuration.")


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


async def get_radiators(token, envID):
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
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=graphql_query, headers=headers
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    payload = json.loads(data["data"]["getShadow"]["payload"])
                    _LOGGER.debug(f"Payload retrieved from API: {payload}")

                    return extract_device_info(payload["state"]["desired"])
                else:
                    _LOGGER.error(f"API request error: {response.status}")
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

    def find_device_keys(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key.endswith(nam_suffix) and not key.startswith(exclude_suffix):
                    device_info = {
                        "serial": value,
                        "temperature": 0,  # Default a 0 se non trovata
                    }
                    corresponding_tmp_key = key[: -len(nam_suffix)] + tmp_suffix
                    if corresponding_tmp_key in obj:
                        tmp_value = obj[corresponding_tmp_key]
                        device_info["temperature"] = (
                            float(tmp_value) / 10 if tmp_value is not None else 0
                        )

                    devices_info.append(device_info)
                find_device_keys(value)
        elif isinstance(obj, list):
            for item in obj:
                find_device_keys(item)

    find_device_keys(payload)
    return devices_info


class RadiatorClimate(ClimateEntity):
    """Representation of a radiator climate entity."""

    def __init__(self, radiator, token, envID):
        self._radiator = radiator
        self._name = f"Radiator {radiator['serial']}"
        self._unique_id = f"radiator_{radiator['serial']}"
        self._current_temperature = radiator.get("temperature", 0)
        self._token = token
        self._envID = envID
        self._state = True  # Assume acceso per default

        # Aggiungi qui le modalità HVAC supportate
        self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]  # Usa HVACMode
        self._attr_hvac_mode = HVACMode.HEAT if self._state else HVACMode.OFF
        self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

    @property
    def name(self):
        """Return the name of the climate device."""
        return self._name

    @property
    def unique_id(self):
        """Return a unique ID for the climate device."""
        return self._unique_id

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return UnitOfTemperature.CELSIUS  # Usa UnitOfTemperature

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._current_temperature

    @property
    def hvac_mode(self):
        """Return current HVAC mode."""
        return self._attr_hvac_mode

    @property
    def hvac_modes(self):
        """Return available HVAC modes."""
        return self._attr_hvac_modes

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target HVAC mode."""
        if hvac_mode == HVACMode.OFF:
            _LOGGER.debug(f"Setting {self._radiator['serial']} to OFF")
            await self._set_radiator_state(False)
        elif hvac_mode == HVACMode.HEAT:
            _LOGGER.debug(f"Setting {self._radiator['serial']} to HEAT")
            await self._set_radiator_state(True)
        else:
            _LOGGER.error(f"Unsupported HVAC mode: {hvac_mode}")
            return

        # Aggiorna la modalità HVAC attuale
        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()

    async def _set_radiator_state(self, state):
        """Send request to set the radiator state."""
        _LOGGER.debug(
            f"Setting radiator state: {self._radiator['serial']} to {'on' if state else 'off'}"
        )

        url = "https://flqpp5xzjzacpfpgkloiiuqizq.appsync-api.eu-west-1.amazonaws.com/graphql"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

        payload = {
            "operationName": "UpdateShadow",
            "variables": {
                "envId": self._envID,
                "payload": json.dumps(
                    {"state": {"desired": {"PCM_ENB": 1 if state else 0}}}
                ),
            },
            "query": "mutation UpdateShadow($envId: ID!, $payload: AWSJSON!) {\n asyncUpdateShadow(envId: $envId, payload: $payload) {\n status\n code\n message\n payload\n __typename\n }\n}\n",
        }

        _LOGGER.debug(f"Payload sent: {payload}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    _LOGGER.debug(
                        f"API response: {response.status}, {await response.text()}"
                    )
                    if response.status == 200:
                        _LOGGER.debug(
                            f"Radiator state {self._radiator['serial']} updated successfully."
                        )
                        self._state = state
                    else:
                        _LOGGER.error(
                            f"Error updating radiator state {self._radiator['serial']}: {response.status}"
                        )
        except Exception as e:
            _LOGGER.error(
                f"Error setting radiator state {self._radiator['serial']}: {e}"
            )

    async def async_update(self):
        """Fetch new state data for this climate entity."""
        _LOGGER.info(f"Updating radiator climate {self._radiator['serial']}")
        self._state = self._radiator["temperature"]