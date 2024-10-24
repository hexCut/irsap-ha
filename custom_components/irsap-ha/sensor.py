from .const import DOMAIN, USER_POOL_ID, CLIENT_ID, REGION
import asyncio
import logging
import time
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceRegistry
import aiohttp
import json
from warrant import Cognito

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up sensor platform."""
    envID = config_entry.data["envID"]
    username = config_entry.data["username"]
    password = config_entry.data["password"]

    token = await hass.async_add_executor_job(login_with_srp, username, password)

    if token and envID:
        _LOGGER.debug("Token and envID successfully obtained. Retrieving sensors.")

        # Salviamo token ed envID nel contesto di Home Assistant
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN]["token"] = token
        hass.data[DOMAIN]["envID"] = envID
        hass.data[DOMAIN]["username"] = username
        hass.data[DOMAIN]["password"] = password

        sensor_data = await get_sensor_data(token, envID)
        if sensor_data:
            device_name = sensor_data["name"]
            device_unique_id = (
                f"radiator_{device_name.replace(' ', '_').lower()}_device"
            )
            device_info = {
                "identifiers": {(DOMAIN, device_unique_id)},
                "name": device_name,
                "model": "Radiator",
                "manufacturer": "IRSAP",
                "serial_number": sensor_data["eid"],
                "sw_version": sensor_data["ever"],
            }

            # Crea un dispositivo
            RadiatorDevice(device_name, device_unique_id)

            sensor_entities = []

            # Aggiungi i sensori al dispositivo
            temperature_sensor = RadiatorSensor(
                name=device_name + " Temperature",
                sensor_type="temperature",
                value=sensor_data["current_temperature"],
                unique_id=f"{device_name}_temperature",
                unit_of_measurement="°C",
                device_info=device_info,  # Passa le informazioni sul dispositivo
            )
            humidity_sensor = RadiatorSensor(
                name=device_name + " Humidity",
                sensor_type="humidity",
                value=sensor_data["humidity"],
                unique_id=f"{device_name}_humidity",
                unit_of_measurement="%",
                device_info=device_info,
            )
            min_temperature_sensor = RadiatorSensor(
                name=device_name + " Min Temperature",
                sensor_type="temperature",
                value=sensor_data["min_temperature"],
                unique_id=f"{device_name}_min_temperature",
                unit_of_measurement="°C",
                device_info=device_info,
            )
            max_temperature_sensor = RadiatorSensor(
                name=device_name + " Max Temperature",
                sensor_type="temperature",
                value=sensor_data["max_temperature"],
                unique_id=f"{device_name}_max_temperature",
                unit_of_measurement="°C",
                device_info=device_info,
            )

            sensor_entities.append(temperature_sensor)
            sensor_entities.append(min_temperature_sensor)
            sensor_entities.append(max_temperature_sensor)
            sensor_entities.append(humidity_sensor)

            # Registra i sensori
            async_add_entities(sensor_entities, True)
            _LOGGER.debug(
                f"Created {len(sensor_entities)} sensors for device '{device_name}'."
            )
        else:
            _LOGGER.warning("No sensors found in the API.")
    else:
        _LOGGER.error("Unable to obtain the token or envID. Check configuration.")


def login_with_srp(username, password):
    "Log in and obtain the access token using Warrant."
    try:
        u = Cognito(USER_POOL_ID, CLIENT_ID, username=username, user_pool_region=REGION)
        u.authenticate(password=password)
        _LOGGER.debug(f"Access Token: {u.access_token}")
        return u.access_token
    except Exception as e:
        _LOGGER.error(f"Error during login: {e}")
        return None


async def get_sensor_data(token, envID):
    "Fetch radiator data from the API."
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


def extract_device_info(payload):
    # Inizializza un dizionario per memorizzare le informazioni estratte
    device_info = {}

    # Estrai il nome del sensore dalla chiave "E_NAM"
    if "E_NAM" in payload:
        device_info["name"] = payload["E_NAM"]

    # Estrai le informazioni sulle temperature dalla chiave "E_WDT"
    if "E_WTD" in payload:
        wdt_data = payload["E_WTD"]
        device_info["current_temperature"] = (
            wdt_data["current"]["temperature"] / 10
        )  # Converti in gradi
        device_info["humidity"] = wdt_data["current"]["humidity"]
        device_info["min_temperature"] = (
            wdt_data["dayDetails"]["temperatures"]["min"] / 10
        )  # Converti in gradi
        device_info["max_temperature"] = (
            wdt_data["dayDetails"]["temperatures"]["max"] / 10
        )  # Converti in gradi

    # Estrai le informazioni sull'indirizzo dalla chiave "E_LOC"
    if "E_LOC" in payload:
        loc_data = payload["E_LOC"]
        address = loc_data["address"]
        device_info["latitude"], device_info["longitude"] = map(
            float, loc_data["latLon"].split(",")
        )
        device_info["city"] = address["city"]
        device_info["country"] = address["country"]
        device_info["postal_code"] = address["postalCode"]
        device_info["state"] = address["state"]
        device_info["street"] = address["street"]
        device_info["iso"] = address["iso"]

    if "E_ID" in payload:
        device_info["eid"] = payload["E_ID"]

    if "E_VER" in payload:
        device_info["ever"] = payload["E_VER"]

    return device_info


def extract_sensor_data(sensor_data, token, envID):
    entities = []

    # Nome base del sensore
    base_name = sensor_data["name"]

    # Creazione di sensori per ogni informazione
    if "current_temperature" in sensor_data:
        entities.append(
            RadiatorSensor(
                base_name,
                "Current Temperature",
                sensor_data["current_temperature"],
                "°C",
            )
        )

    if "humidity" in sensor_data:
        entities.append(
            RadiatorSensor(base_name, "Humidity", sensor_data["humidity"], "%")
        )

    if "min_temperature" in sensor_data:
        entities.append(
            RadiatorSensor(
                base_name, "Min Temperature", sensor_data["min_temperature"], "°C"
            )
        )

    if "max_temperature" in sensor_data:
        entities.append(
            RadiatorSensor(
                base_name, "Max Temperature", sensor_data["max_temperature"], "°C"
            )
        )

    # Altre metriche come latitudine e longitudine, se necessario, possono essere aggiunte

    return entities


class RadiatorDevice:
    def __init__(self, name, unique_id):
        self._name = name
        self._unique_id = unique_id
        self._sensors = []

    @property
    def name(self):
        return self._name

    @property
    def unique_id(self):
        return self._unique_id

    def add_sensor(self, sensor):
        self._sensors.append(sensor)

    @property
    def sensors(self):
        return self._sensors


class RadiatorSensor(SensorEntity):
    def __init__(
        self, name, sensor_type, value, unique_id, unit_of_measurement, device_info=None
    ):
        self._name = name
        self._sensor_type = sensor_type
        self._value = value
        self._unique_id = unique_id
        self._unit_of_measurement = unit_of_measurement
        self._device_info = device_info  # Aggiungi questa riga
        self._state = value  # Imposta lo stato iniziale

    @property
    def unique_id(self):
        return self._unique_id

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state

    @property
    def unit_of_measurement(self):
        return self._unit_of_measurement

    @property
    def device_info(self):
        return self._device_info
