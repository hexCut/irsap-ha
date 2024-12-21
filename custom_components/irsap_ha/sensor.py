from .const import DOMAIN, USER_POOL_ID, CLIENT_ID, REGION
import logging
from homeassistant.components.sensor import SensorEntity, datetime
import aiohttp
import json
from warrant import Cognito
import re
from .device_manager import device_manager
import pytz
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    from .climate import RadiatorClimate  # Importa RadiatorClimate qui

    envID = config_entry.data["envID"]
    username = config_entry.data["username"]
    password = config_entry.data["password"]

    token = await hass.async_add_executor_job(login_with_srp, username, password)

    if token and envID:
        _LOGGER.debug("Token and envID successfully obtained. Retrieving sensors.")

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN]["token"] = token
        hass.data[DOMAIN]["envID"] = envID
        hass.data[DOMAIN]["username"] = username
        hass.data[DOMAIN]["password"] = password

        devices = device_manager.get_devices()  # Ottieni i dispositivi dal manager
        _LOGGER.debug(
            f"Devices found: {[device.radiator['serial'] for device in devices]}"
        )

        if not devices:
            _LOGGER.error(
                "No devices found. Please ensure that climate entities are set up correctly."
            )
            return

        sensors = await get_sensor_data(token, envID)
        sensor_entities = []

        for r in sensors:
            # Trova il dispositivo associato al sensore
            device = next(
                (d for d in devices if d.radiator["serial"] == r["serial"]), None
            )

            if device is not None:
                sensor_entity = RadiatorSensor(
                    r, device, unique_id=f"{r['serial']}_ip_address"
                )
                sensor_entities.append(sensor_entity)
                # Aggiungi tutti i sensori necessari per ciascun dispositivo
                sensor_entities.append(
                    LastUpdateSensor(r, device, unique_id=f"{r['serial']}_last_update")
                )
                sensor_entities.append(
                    WifiSignalSensor(r, device, unique_id=f"{r['serial']}_wifi_signal")
                )
                sensor_entities.append(
                    PiloteEnableSensor(
                        r, device, unique_id=f"{r['serial']}_pilote_enable"
                    )
                )
                sensor_entities.append(
                    PiloteStatusSensor(
                        r, device, unique_id=f"{r['serial']}_pilote_status"
                    )
                )
                sensor_entities.append(
                    StandbySensor(r, device, unique_id=f"{r['serial']}_standby")
                )
                sensor_entities.append(
                    OpenWindowEnabledSensor(
                        r, device, unique_id=f"{r['serial']}_openwindow_enabled"
                    )
                )
                sensor_entities.append(
                    OpenWindowOffsetSensor(
                        r, device, unique_id=f"{r['serial']}_openwindow_offset"
                    )
                )
                sensor_entities.append(
                    TemperatureOffsetSensor(
                        r, device, unique_id=f"{r['serial']}_temperature_offset"
                    )
                )
                sensor_entities.append(
                    HysteresisSensor(r, device, unique_id=f"{r['serial']}_hysteresis")
                )
                sensor_entities.append(
                    VocSensor(r, device, unique_id=f"{r['serial']}_voc")
                )
                sensor_entities.append(
                    Co2Sensor(r, device, unique_id=f"{r['serial']}_co2")
                )
                sensor_entities.append(
                    OpenWindowDetectedSensor(
                        r, device, unique_id=f"{r['serial']}_openwindow_detected"
                    )
                )
                sensor_entities.append(
                    LockSensor(r, device, unique_id=f"{r['serial']}_lock")
                )  # Child lock sensor
            else:
                _LOGGER.debug(f"No matching device found for sensor {r['serial']}")

        async_add_entities(sensor_entities, True)
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


import re


def extract_device_info(
    payload,
    nam_suffix="_NAM",
    tmp_suffix="_TMP",
    enb_suffix="_ENB",
    exclude_suffix="E_NAM",
):
    devices_info = []

    # Suffixi di interesse per le chiavi
    suffixes = [
        "_CNT",
        "_FWV",
        "_TYP",
        "_SLV",
        "_LUP",
        "_X_ipAddress",
        "_X_filPiloteEnabled",
        "_X_filPiloteStatus",
        "_X_standby",
        "_X_OpenWindowSensorEnabled",
        "_X_OpenWindowDetected",
        "_X_OpenWindowSensorOffTime",
        "_X_temperatureSensorOffset",
        "_X_hysteresis",
        "_X_vocValue",
        "_X_co2Value",
        "_X_lock",
    ]

    # Liste per raccogliere le chiavi
    nam_keys = []
    cnt_keys = []
    fwv_keys = []
    typ_keys = []
    slv_keys = []
    lup_keys = []
    ip_keys = []
    pilote_enb_keys = []
    pilote_sta_keys = []
    stand_keys = []
    openwin_enab_keys = []
    openwin_dect_keys = []
    openwin_off_keys = []
    temp_off_keys = []
    hyst_keys = []
    voc_keys = []
    co2_keys = []
    lock_keys = []

    def find_device_keys(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                # Raccogli chiavi _NAM e aggiungi i dettagli iniziali
                if key.endswith(nam_suffix) and not key.startswith(exclude_suffix):
                    device_info = {
                        "serial": value,
                        "temperature": 0,  # Default a 0 se non trovata
                        "state": "OFF",  # Default a OFF se non trovato
                    }
                    nam_keys.append((key, device_info))

                # Controlla se la chiave finisce con uno dei suffissi
                if any(key.endswith(suffix) for suffix in suffixes):
                    # Aggiungi la chiave alla lista corrispondente
                    if key.endswith("_CNT"):
                        cnt_keys.append((key, value))
                    elif key.endswith("_FWV"):
                        fwv_keys.append((key, value))
                    elif key.endswith("_TYP"):
                        typ_keys.append((key, value))
                    elif key.endswith("_SLV"):
                        slv_keys.append((key, value))
                    elif key.endswith("_LUP"):
                        lup_keys.append((key, value))
                    elif key.endswith("_X_ipAddress"):
                        ip_keys.append((key, value))
                    elif key.endswith("_X_filPiloteEnabled"):
                        pilote_enb_keys.append((key, value))
                    elif key.endswith("_X_filPiloteStatus"):
                        pilote_sta_keys.append((key, value))
                    elif key.endswith("_X_standby"):
                        stand_keys.append((key, value))
                    elif key.endswith("_X_OpenWindowSensorEnabled"):
                        openwin_enab_keys.append((key, value))
                    elif key.endswith("_X_OpenWindowDetected"):
                        openwin_dect_keys.append((key, value))
                    elif key.endswith("_X_OpenWindowSensorOffTime"):
                        openwin_off_keys.append((key, value))
                    elif key.endswith("_X_temperatureSensorOffset"):
                        temp_off_keys.append((key, value))
                    elif key.endswith("_X_hysteresis"):
                        hyst_keys.append((key, value))
                    elif key.endswith("_X_vocValue"):
                        voc_keys.append((key, value))
                    elif key.endswith("_X_co2Value"):
                        co2_keys.append((key, value))
                    elif key.endswith("_X_lock"):
                        lock_keys.append((key, value))

                # Ricorsione per esplorare eventuali chiavi annidate
                find_device_keys(value)
        elif isinstance(obj, list):
            for item in obj:
                find_device_keys(item)

    # Esegui la ricerca nel payload
    find_device_keys(payload)

    # Associa ogni _NAM ai suoi corrispondenti attributi
    for i, (nam_key, device_info) in enumerate(nam_keys):
        base_key = nam_key[: -len(nam_suffix)]
        corresponding_tmp_key = base_key + tmp_suffix
        corresponding_enb_key = base_key + enb_suffix

        # Trova la temperatura
        if corresponding_tmp_key in payload:
            tmp_value = payload.get(corresponding_tmp_key)
            device_info["temperature"] = (
                float(tmp_value) / 10 if tmp_value is not None else 0
            )

        # Trova lo stato (ON/OFF)
        if corresponding_enb_key in payload:
            enb_value = payload.get(corresponding_enb_key)
            device_info["state"] = "HEAT" if enb_value == 1 else "OFF"

        # Associa altri dati (es. MAC, firmware, IP, etc.)
        if i < len(cnt_keys):
            device_info["mac"] = cnt_keys[i][1]
        if i < len(fwv_keys):
            device_info["firmware"] = fwv_keys[i][1]
        if i < len(typ_keys):
            device_info["model"] = typ_keys[i][1]
        if i < len(slv_keys):
            device_info["wifi_signal"] = slv_keys[i][1]
        if i < len(lup_keys):
            device_info["last_update"] = lup_keys[i][1]
        if i < len(ip_keys):
            device_info["ip_address"] = ip_keys[i][1]
        if i < len(pilote_enb_keys):
            device_info["pilote_enable"] = pilote_enb_keys[i][1]
        if i < len(pilote_sta_keys):
            device_info["pilote_status"] = pilote_sta_keys[i][1]
        if i < len(stand_keys):
            device_info["standby"] = stand_keys[i][1]
        if i < len(openwin_enab_keys):
            device_info["open_window_enabled"] = openwin_enab_keys[i][1]
        if i < len(openwin_dect_keys):
            device_info["openwindow_detected"] = openwin_dect_keys[i][1]
        if i < len(openwin_off_keys):
            device_info["openwindow_offset"] = openwin_off_keys[i][1]
        if i < len(temp_off_keys):
            device_info["temperature_offset"] = temp_off_keys[i][1]
        if i < len(hyst_keys):
            device_info["hysteresis"] = hyst_keys[i][1]
        if i < len(voc_keys):
            device_info["voc"] = voc_keys[i][1]
        if i < len(co2_keys):
            device_info["co2"] = co2_keys[i][1]
        if i < len(lock_keys):
            device_info["lock"] = lock_keys[i][1]

        devices_info.append(device_info)

    return devices_info


class RadiatorSensor(SensorEntity):
    def __init__(self, radiator, device, unique_id):
        self._radiator = radiator
        self._device = device  # Store device reference
        self._attr_name = f"{radiator['serial']} IP Address"
        self._attr_unique_id = unique_id
        self._attr_icon = "mdi:ip"
        self._radiator_serial = radiator["serial"]
        self._model = radiator.get("model", "Modello Sconosciuto")
        self._attr_native_value = radiator.get("ip_address", "IP non disponibile")
        self._sw_version = radiator.get("firmware")

    @property
    def native_value(self):
        return self._attr_native_value

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def device_info(self):
        """Associa il sensore al dispositivo climate con il seriale corrispondente."""
        return {
            "identifiers": {
                (DOMAIN, self._radiator["serial"])
            },  # Use device serial number
            "name": f"{self._radiator['serial']}",
            "model": self._radiator.get("model", "Unknown Model"),
            "manufacturer": "IRSAP",
            "sw_version": self._radiator.get("firmware", "Unknown Firmware"),
        }


class BaseRadiatorSensor(SensorEntity):
    """Base class for radiator sensors."""

    def __init__(
        self, radiator, device, unique_id, attr_name, icon, data_key, formatter=None
    ):
        self._radiator = radiator
        self._device = device
        self._attr_name = f"{radiator['serial']} {attr_name}"
        self._attr_unique_id = unique_id
        self._attr_icon = icon
        self._attr_native_value = None
        self._data_key = data_key
        self._formatter = formatter

    @property
    def native_value(self):
        """Retrieve and format the value for the sensor."""
        raw_value = self._radiator.get(self._data_key)
        if raw_value is None:
            return "N/A"
        if self._formatter:
            return self._formatter(raw_value)
        return raw_value

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._radiator["serial"])},
            "name": f"{self._radiator['serial']}",
            "model": self._radiator.get("model", "Unknown Model"),
            "manufacturer": "IRSAP",
            "sw_version": self._radiator.get("firmware", "Unknown Firmware"),
        }

    async def async_update(self):
        """Update the sensor value periodically."""
        self._attr_native_value = self.native_value
        _LOGGER.debug(f"Updated {self._attr_name} to {self._attr_native_value}")


class WifiSignalSensor(BaseRadiatorSensor):
    def __init__(self, radiator, device, unique_id):
        super().__init__(
            radiator,
            device,
            unique_id,
            "WiFi Signal Strength",
            "mdi:wifi",
            "wifi_signal",
        )

    @property
    def native_value(self):
        """Return the WiFi signal strength in dBm."""
        return self._radiator.get("wifi_signal", "N/A")


class PiloteEnableSensor(BaseRadiatorSensor):
    def __init__(self, radiator, device, unique_id):
        super().__init__(
            radiator, device, unique_id, "Pilote Enable", "mdi:power", "pilote_enable"
        )

    @property
    def native_value(self):
        """Return 'Enabled' if pilote feature is active (1), otherwise 'Disabled' (0)."""
        status = self._radiator.get("pilote_enable", None)
        if status == 1:
            return "Enabled"
        elif status == 0:
            return "Disabled"
        return "Unknown"  # Default if status is not available


class PiloteStatusSensor(BaseRadiatorSensor):
    def __init__(self, radiator, device, unique_id):
        super().__init__(
            radiator,
            device,
            unique_id,
            "Pilote Status",
            "mdi:check-circle",
            "pilote_status",
        )

    @property
    def native_value(self):
        """Return 'Active' if pilote is currently active (1), otherwise 'Inactive' (0)."""
        status = self._radiator.get("pilote_status", None)
        if status == 1:
            return "Active"
        elif status == 0:
            return "Inactive"
        return "Unknown"  # Default if status is not available


class StandbySensor(BaseRadiatorSensor):
    def __init__(self, radiator, device, unique_id):
        super().__init__(radiator, device, unique_id, "Standby", "mdi:sleep", "standby")

    @property
    def native_value(self):
        """Return 'Yes' if standby feature is active (1), otherwise 'No' (0)."""
        status = self._radiator.get("standby", None)
        if status == 1:
            return "Yes"
        elif status == 0:
            return "No"
        return "Unknown"  # Default if status is not available


class OpenWindowEnabledSensor(BaseRadiatorSensor):
    def __init__(self, radiator, device, unique_id):
        super().__init__(
            radiator,
            device,
            unique_id,
            "Open Window Enabled",
            "mdi:window-open",
            "open_window_enabled",
        )

    @property
    def native_value(self):
        """Return 'Enabled' if open window feature is active (1), otherwise 'Disabled' (0)."""
        status = self._radiator.get("open_window_enabled", None)
        if status == 1:
            return "Enabled"
        elif status == 0:
            return "Disabled"
        return "Unknown"  # Default if status is not available


class OpenWindowOffsetSensor(BaseRadiatorSensor):
    def __init__(self, radiator, device, unique_id):
        super().__init__(
            radiator,
            device,
            unique_id,
            "Open Window Offset",
            "mdi:window-closed",
            "openwindow_offset",
        )


class TemperatureOffsetSensor(BaseRadiatorSensor):
    def __init__(self, radiator, device, unique_id):
        super().__init__(
            radiator,
            device,
            unique_id,
            "Temperature Offset",
            "mdi:thermometer",
            "temperature_offset",
        )

    @property
    def native_value(self):
        """Convert the temperature offset from two digits to a decimal format."""
        offset = self._radiator.get("temperature_offset", None)
        if offset is not None:
            return offset / 10.0  # Convert two-digit value to decimal
        return "Unknown"  # Default if offset is not available


class HysteresisSensor(BaseRadiatorSensor):
    def __init__(self, radiator, device, unique_id):
        super().__init__(
            radiator, device, unique_id, "Hysteresis", "mdi:sine-wave", "hysteresis"
        )


class VocSensor(BaseRadiatorSensor):
    def __init__(self, radiator, device, unique_id):
        super().__init__(radiator, device, unique_id, "VOC", "mdi:air-filter", "voc")


class Co2Sensor(BaseRadiatorSensor):
    def __init__(self, radiator, device, unique_id):
        super().__init__(radiator, device, unique_id, "CO2", "mdi:molecule-co2", "co2")


class OpenWindowDetectedSensor(BaseRadiatorSensor):
    def __init__(self, radiator, device, unique_id):
        super().__init__(
            radiator,
            device,
            unique_id,
            "Open Window Detected",
            "mdi:window-open",
            "openwindow_detected",
        )

    @property
    def native_value(self):
        """Return 'Open' if window is detected open (1), otherwise 'Closed' (0)."""
        status = self._radiator.get("openwindow_detected", None)
        if status == 1:
            return "Open"
        elif status == 0:
            return "Closed"
        return "Unknown"  # Default if status is not available


class LastUpdateSensor(SensorEntity):
    def __init__(self, radiator, device, unique_id):
        self._radiator = radiator
        self._device = device  # Store device reference
        self._attr_name = f"{radiator['serial']} Last Update"
        self._attr_unique_id = unique_id
        self._attr_icon = "mdi:update"
        self._attr_native_value = None  # Initialize the sensor value

    @property
    def native_value(self):
        # Retrieve the last update timestamp
        last_update_raw = self._radiator.get("last_update")

        # Convert the timestamp to a readable format if it exists
        if last_update_raw:
            # Parse the ISO string
            last_update_dt = datetime.fromisoformat(
                last_update_raw.replace("Z", "+00:00")
            )

            # Convert to the local timezone configured in Home Assistant
            local_tz = dt_util.DEFAULT_TIME_ZONE
            last_update_local = last_update_dt.astimezone(local_tz)
            return last_update_local.strftime(
                "%d-%m-%Y %H:%M"
            )  # Format as "DD-MM-YYYY HH:MM"

        return "N/A"  # Return a default if `last_update` is missing

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._radiator["serial"])},
            "name": f"{self._radiator['serial']}",
            "model": self._radiator.get("model", "Unknown Model"),
            "manufacturer": "IRSAP",
            "sw_version": self._radiator.get("firmware", "Unknown Firmware"),
        }

    async def async_update(self):
        """Update the sensor value periodically."""
        self._attr_native_value = (
            self.native_value
        )  # Trigger conversion in native_value
        _LOGGER.debug(f"Updated {self._attr_name} to {self._attr_native_value}")


class LockSensor(BaseRadiatorSensor):
    def __init__(self, radiator, device, unique_id):
        super().__init__(radiator, device, unique_id, "Child Lock", "mdi:lock", "lock")

    @property
    def native_value(self):
        """Return 'Locked' if child lock is active (1), otherwise 'Unlocked' (0)."""
        lock_status = self._radiator.get("lock", None)
        if lock_status == 1:
            return "Locked"
        elif lock_status == 0:
            return "Unlocked"
        return "Unknown"  # Default value if lock status is not available
