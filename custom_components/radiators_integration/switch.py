import aiohttp
import logging
import json
from homeassistant.components.switch import SwitchEntity

_LOGGER = logging.getLogger(__name__)


async def setup_switch(hass, config_entry, async_add_entities):
    """Setup the switch platform for an entry."""
    _LOGGER.debug("Starting async setup entry for switch platform.")

    token = config_entry["data"]["token"]
    envID = config_entry["data"]["envID"]

    if token and envID:
        _LOGGER.debug("Token and envID successfully obtained. Retrieving radiators.")
        radiators = await get_radiators(token, envID)
        if radiators:
            switches = []
            for radiator in radiators:
                _LOGGER.debug(f"Adding switch for radiator: {radiator['serial']}")
                switches.append(RadiatorSwitch(radiator, token, envID))
            async_add_entities(switches, True)
            _LOGGER.debug(f"Created {len(switches)} switches.")
        else:
            _LOGGER.warning("No radiators found in the API.")
    else:
        _LOGGER.error("Unable to obtain the token or envID. Check configuration.")


async def get_radiators(token, envID):
    """Retrieve radiator data from the API asynchronously."""
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
    payload,
    nam_suffix="_NAM",
    srl_suffix="_SRL",
    enb_suffix="_ENB",
    exclude_suffix="E_NAM",
):
    devices_info = []

    def find_device_keys(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key.startswith(exclude_suffix):
                    continue

                if key.endswith(nam_suffix) and value:
                    device_info = {
                        "serial": None,
                        "is_on": False,
                        "name": value,
                    }

                    corresponding_srl_key = key[: -len(nam_suffix)] + srl_suffix
                    if corresponding_srl_key in obj and obj[corresponding_srl_key]:
                        device_info["serial"] = obj[corresponding_srl_key]

                    corresponding_enb_key = key[: -len(nam_suffix)] + enb_suffix
                    if corresponding_enb_key in obj:
                        enb_value = obj[corresponding_enb_key]
                        device_info["is_on"] = (
                            bool(int(enb_value)) if enb_value else False
                        )

                    devices_info.append(device_info)

                find_device_keys(value)
        elif isinstance(obj, list):
            for item in obj:
                find_device_keys(item)

    find_device_keys(payload)
    return devices_info


class RadiatorSwitch(SwitchEntity):
    """Switch to turn radiators on/off."""

    def __init__(self, radiator, token, envID):
        self._radiator = radiator
        self._token = token
        self._state = radiator["is_on"]
        self._name = radiator["name"]
        self._envID = envID

    @property
    def name(self):
        """Return the name of the switch."""
        return self._name

    @property
    def is_on(self):
        """Return the state of the switch."""
        return self._state

    async def turn_on(self, **kwargs):
        """Turn on the radiator."""
        _LOGGER.debug(f"Turn on called for radiator {self._radiator['serial']}")
        await self._set_radiator_state(True)

    async def turn_off(self, **kwargs):
        """Turn off the radiator."""
        _LOGGER.debug(f"Turn off called for radiator {self._radiator['serial']}")
        await self._set_radiator_state(False)

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
            "query": "mutation UpdateShadow($envId: ID!, $payload: AWSJSON!) {\n  asyncUpdateShadow(envId: $envId, payload: $payload) {\n    status\n    code\n    message\n    payload\n    __typename\n  }\n}\n",
        }

        _LOGGER.debug(f"Payload sent: {payload}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    _LOGGER.debug(f"API response: {response.status}, {response.text}")
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
        """Update the switch state by querying the API."""
        _LOGGER.debug(f"Updating radiator state {self._radiator['serial']}")

        url = "https://flqpp5xzjzacpfpgkloiiuqizq.appsync-api.eu-west-1.amazonaws.com/graphql"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

        graphql_query = {
            "operationName": "GetShadow",
            "variables": {"envId": self._envID},
            "query": "query GetShadow($envId: ID!) {\n  getShadow(envId: $envId) {\n    envId\n    payload\n    __typename\n  }\n}\n",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=headers, json=graphql_query
                ) as response:
                    if response.status == 200:
                        data = response.json()
                        payload = json.loads(data["data"]["getShadow"]["payload"])
                        _LOGGER.debug(f"Payload updated from API: {payload}")

                        self._state = (
                            bool(int(payload["state"]["desired"]["PCM_ENB"]))
                            if payload["state"]["desired"]["PCM_ENB"]
                            else False
                        )
                    else:
                        _LOGGER.error(
                            f"API request error during state update: {response.status}"
                        )
        except Exception as e:
            _LOGGER.error(f"Error updating radiator state: {e}")
