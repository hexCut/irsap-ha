from .const import DOMAIN
import logging
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
    datetime,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .device_manager import device_manager
from .shadow import device_values
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    devices = device_manager.get_devices()  # Ottieni i dispositivi dal manager
    _LOGGER.debug(
        f"Devices found: {[device.radiator['serial'] for device in devices]}"
    )

    if not devices:
        _LOGGER.error(
            "No devices found. Please ensure that climate entities are set up correctly."
        )
        return

    # Dati dei sensori dal GetShadow già fatto dal coordinator
    sensors = extract_device_info(coordinator.desired)
    sensor_entities = []
    unsupported = {}  # unique_id -> (serial, sensor class)

    for r in sensors:
        # Trova il dispositivo associato al sensore
        device = next(
            (d for d in devices if d.radiator["serial"] == r["serial"]), None
        )

        if device is not None:
            for sensor_cls, suffix in SENSOR_TYPES:
                unique_id = f"{r['serial']}_{suffix}"
                supported = sensor_cls.is_supported(r)
                # Una misura che il radiatore non ha viene disattivata, non
                # cancellata: se in seguito arriva un valore vero si riattiva
                _sync_disabled_state(hass, unique_id, supported)
                if not supported:
                    unsupported[unique_id] = (r["serial"], sensor_cls)
                entity = sensor_cls(coordinator, r, device, unique_id)
                entity._attr_entity_registry_enabled_default = supported
                sensor_entities.append(entity)
        else:
            _LOGGER.debug(f"No matching device found for sensor {r['serial']}")

    # I valori arrivano già dal coordinator: niente aggiornamento prima dell'aggiunta
    async_add_entities(sensor_entities)

    @callback
    def _re_enable_when_reported():
        """A sensor disabled at setup (e.g. a CO2 sensor still warming up and
        reporting 65535) is re-enabled as soon as a real value arrives; Home
        Assistant then reloads the entry and adds it."""
        if not unsupported:
            return
        radiators = {r["serial"]: r for r in extract_device_info(coordinator.desired)}
        for unique_id, (serial, sensor_cls) in list(unsupported.items()):
            radiator = radiators.get(serial)
            if radiator is not None and sensor_cls.is_supported(radiator):
                del unsupported[unique_id]
                _sync_disabled_state(hass, unique_id, True)

    config_entry.async_on_unload(
        coordinator.async_add_listener(_re_enable_when_reported)
    )


# Value the firmware reports for a measurement the radiator doesn't have
NOT_AVAILABLE = 65535


def _sync_disabled_state(hass, unique_id, supported):
    """Disable an existing sensor the radiator doesn't support, and re-enable it
    once it does. Only entities disabled by the integration are re-enabled:
    a sensor the user disabled stays disabled."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    if entity_id is None:
        return
    entry = registry.async_get(entity_id)
    if not supported and entry.disabled_by is None:
        _LOGGER.info(f"Disabling {entity_id}: not supported by this radiator")
        registry.async_update_entity(
            entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION
        )
    elif supported and entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION:
        _LOGGER.info(f"Re-enabling {entity_id}: the radiator now reports it")
        registry.async_update_entity(entity_id, disabled_by=None)


# Device fields read for each zone (name used here -> key suffix)
SENSOR_DEVICE_FIELDS = {
    "mac": "_CNT",
    "firmware": "_FWV",
    "model": "_TYP",
    "wifi_signal": "_SLV",
    "last_update": "_LUP",
    "ip_address": "_X_ipAddress",
    "pilote_enable": "_X_filPiloteEnabled",
    "pilote_status": "_X_filPiloteStatus",
    "standby": "_X_standby",
    "open_window_enabled": "_X_OpenWindowSensorEnabled",
    "openwindow_detected": "_X_OpenWindowDetected",
    "openwindow_offset": "_X_OpenWindowSensorOffTime",
    "temperature_offset": "_X_temperatureSensorOffset",
    "hysteresis": "_X_hysteresis",
    "voc": "_X_vocValue",
    "co2": "_X_co2Value",
    "lock": "_X_lock",
}


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
        "_AIQ",
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
    aiq_keys = []

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
                    elif key.endswith("_AIQ"):
                        aiq_keys.append((key, value))

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
        if i < len(aiq_keys):
            device_info["aiq"] = aiq_keys[i][1]

        # Con più radiatori l'ordine delle chiavi non basta: la qualità dell'aria
        # è un valore della zona, gli altri del dispositivo collegato alla zona
        if base_key + "_AIQ" in payload:
            device_info["aiq"] = payload[base_key + "_AIQ"]
        device_info.update(device_values(payload, base_key, SENSOR_DEVICE_FIELDS))

        devices_info.append(device_info)

    return devices_info


class RadiatorCoordinatorEntity(CoordinatorEntity):
    """Diagnostic sensor that refreshes its radiator's data from the coordinator."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @classmethod
    def is_supported(cls, radiator):
        """False if the radiator doesn't have this measurement at all."""
        return True

    @callback
    def _handle_coordinator_update(self) -> None:
        serial = self._radiator["serial"]
        for radiator in extract_device_info(self.coordinator.desired):
            if radiator["serial"] == serial:
                self._radiator = radiator
                break
        else:
            _LOGGER.debug(
                f"Radiator {serial} not in the latest data, keeping last values"
            )
        super()._handle_coordinator_update()


class RadiatorSensor(RadiatorCoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, radiator, device, unique_id):
        super().__init__(coordinator)
        self._radiator = radiator
        self._device = device  # Store device reference
        self._attr_name = f"{radiator['serial']} IP Address"
        self._attr_unique_id = unique_id
        self._attr_icon = "mdi:ip"
        self._radiator_serial = radiator["serial"]
        self._model = radiator.get("model", "Modello Sconosciuto")
        self._sw_version = radiator.get("firmware")

    @property
    def native_value(self):
        return self._radiator.get("ip_address", "IP non disponibile")

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


class BaseRadiatorSensor(RadiatorCoordinatorEntity, SensorEntity):
    """Base class for radiator sensors."""

    def __init__(
        self,
        coordinator,
        radiator,
        device,
        unique_id,
        attr_name,
        icon,
        data_key,
        formatter=None,
    ):
        super().__init__(coordinator)
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


class NumericRadiatorSensor(BaseRadiatorSensor):
    """Sensor with a numeric value; None (unknown) when it isn't available."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _scale = 1  # raw value / _scale (e.g. tenths of a degree -> °C)

    @property
    def native_value(self):
        raw = self._radiator.get(self._data_key)
        if not _is_number(raw) or raw == NOT_AVAILABLE:
            return None
        return raw / self._scale if self._scale != 1 else raw


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class WifiSignalSensor(NumericRadiatorSensor):
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT

    def __init__(self, coordinator, radiator, device, unique_id):
        super().__init__(
            coordinator,
            radiator,
            device,
            unique_id,
            "WiFi Signal Strength",
            "mdi:wifi",
            "wifi_signal",
        )


class PiloteEnableSensor(BaseRadiatorSensor):

    def __init__(self, coordinator, radiator, device, unique_id):
        super().__init__(
            coordinator,
            radiator,
            device,
            unique_id,
            "Pilote Enable",
            "mdi:power",
            "pilote_enable",
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

    def __init__(self, coordinator, radiator, device, unique_id):
        super().__init__(
            coordinator,
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

    def __init__(self, coordinator, radiator, device, unique_id):
        super().__init__(
            coordinator, radiator, device, unique_id, "Standby", "mdi:sleep", "standby"
        )

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

    def __init__(self, coordinator, radiator, device, unique_id):
        super().__init__(
            coordinator,
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


class OpenWindowOffsetSensor(NumericRadiatorSensor):
    """How long the radiator stays off after detecting an open window."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, coordinator, radiator, device, unique_id):
        super().__init__(
            coordinator,
            radiator,
            device,
            unique_id,
            "Open Window Offset",
            "mdi:window-closed",
            "openwindow_offset",
        )


class TemperatureOffsetSensor(NumericRadiatorSensor):
    # A temperature difference: no device class, so HA doesn't convert it
    # as if it were an absolute temperature
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _scale = 10  # tenths of a degree

    def __init__(self, coordinator, radiator, device, unique_id):
        super().__init__(
            coordinator,
            radiator,
            device,
            unique_id,
            "Temperature Offset",
            "mdi:thermometer",
            "temperature_offset",
        )


class HysteresisSensor(NumericRadiatorSensor):
    # A temperature difference, see TemperatureOffsetSensor
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _scale = 10  # tenths of a degree

    def __init__(self, coordinator, radiator, device, unique_id):
        super().__init__(
            coordinator,
            radiator,
            device,
            unique_id,
            "Hysteresis",
            "mdi:sine-wave",
            "hysteresis",
        )


class VocSensor(NumericRadiatorSensor):
    @classmethod
    def is_supported(cls, radiator):
        return _is_number(radiator.get("voc")) and radiator["voc"] != NOT_AVAILABLE

    def __init__(self, coordinator, radiator, device, unique_id):
        super().__init__(
            coordinator, radiator, device, unique_id, "VOC", "mdi:air-filter", "voc"
        )


class Co2Sensor(NumericRadiatorSensor):
    _attr_device_class = SensorDeviceClass.CO2
    _attr_native_unit_of_measurement = "ppm"

    @classmethod
    def is_supported(cls, radiator):
        return _is_number(radiator.get("co2")) and radiator["co2"] != NOT_AVAILABLE

    def __init__(self, coordinator, radiator, device, unique_id):
        super().__init__(
            coordinator, radiator, device, unique_id, "CO2", "mdi:molecule-co2", "co2"
        )


class OpenWindowDetectedSensor(BaseRadiatorSensor):

    def __init__(self, coordinator, radiator, device, unique_id):
        super().__init__(
            coordinator,
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


class LastUpdateSensor(RadiatorCoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, radiator, device, unique_id):
        super().__init__(coordinator)
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


class LockSensor(BaseRadiatorSensor):

    def __init__(self, coordinator, radiator, device, unique_id):
        super().__init__(
            coordinator, radiator, device, unique_id, "Child Lock", "mdi:lock", "lock"
        )

    @property
    def native_value(self):
        """Return 'Locked' if child lock is active (1), otherwise 'Unlocked' (0)."""
        lock_status = self._radiator.get("lock", None)
        if lock_status == 1:
            return "Locked"
        elif lock_status == 0:
            return "Unlocked"
        return "Unknown"  # Default value if lock status is not available


class AIQSensor(BaseRadiatorSensor):

    @classmethod
    def is_supported(cls, radiator):
        return radiator.get("aiq") is not None

    def __init__(self, coordinator, radiator, device, unique_id):
        super().__init__(
            coordinator,
            radiator,
            device,
            unique_id,
            "Air Quality",
            "mdi:air-purifier",
            "aiq",
        )


# Every diagnostic sensor, with the suffix of its unique_id (serial_suffix)
SENSOR_TYPES = [
    (RadiatorSensor, "ip_address"),
    (LastUpdateSensor, "last_update"),
    (WifiSignalSensor, "wifi_signal"),
    (PiloteEnableSensor, "pilote_enable"),
    (PiloteStatusSensor, "pilote_status"),
    (StandbySensor, "standby"),
    (OpenWindowEnabledSensor, "openwindow_enabled"),
    (OpenWindowOffsetSensor, "openwindow_offset"),
    (TemperatureOffsetSensor, "temperature_offset"),
    (HysteresisSensor, "hysteresis"),
    (VocSensor, "voc"),
    (Co2Sensor, "co2"),
    (OpenWindowDetectedSensor, "openwindow_detected"),
    (LockSensor, "lock"),
    (AIQSensor, "aiq"),
]
