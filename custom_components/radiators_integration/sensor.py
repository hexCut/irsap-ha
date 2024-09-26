import aiohttp
import logging
import json
from datetime import timedelta
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.event import async_track_time_interval

_LOGGER = logging.getLogger(__name__)


async def setup_sensor(hass, entry, async_add_entities):
    """Setup the sensor platform for an entry."""
    _LOGGER.debug("Starting async setup entry for sensor platform.")

    token = entry["data"]["token"]
    envID = entry["data"]["envID"]

    if token and envID:
        _LOGGER.debug("Token and envID successfully obtained. Retrieving sensors.")
        sensors = await get_radiators(token, envID)
        if sensors:
            _LOGGER.debug(f"Sensors to be added: {sensors}")
            async_add_entities(sensors, True)
            _LOGGER.debug(f"Created {len(sensors)} sensors.")

            # Pianifica il controllo periodico ogni 10 minuti (600 secondi)
            async_track_time_interval(
                hass,
                lambda now: async_update_sensors(hass, sensors),
                timedelta(minutes=10),
            )
        else:
            _LOGGER.warning("No sensors found in the API.")
    else:
        _LOGGER.error("Unable to obtain the token or envID. Check configuration.")


async def async_update_sensors(hass, sensors):
    """Aggiorna i sensori."""
    _LOGGER.debug("Updating sensors...")
    for sensor in sensors:
        await sensor.async_update()


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

                    devices_info.append(RadiatorTemperatureSensor(device_info))
                # Aggiunge l'informazione del dispositivo
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

    def __init__(self, radiator):
        self._radiator = radiator
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

    async def async_update(self):
        """Update the sensor value."""
        _LOGGER.debug(f"Updating radiator temperature {self._radiator['serial']}")
        # Logic to update the temperature from the API or payload
        self._state = float(
            self._radiator.get("temperature", 0)
        )  # Default to 0 if not found
