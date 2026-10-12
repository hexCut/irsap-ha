import asyncio
import logging
import time
from homeassistant.components import persistent_notification
from homeassistant.components.climate import (
    ClimateEntity,
    HVACMode,
)
from homeassistant.components.climate.const import ClimateEntityFeature
from homeassistant.const import UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, WRITE_SETTLE_TIME
from .api import async_fetch_shadow, async_update_shadow
import json
import re
from .device import RadiatorDevice
from .device_manager import device_manager

_LOGGER = logging.getLogger(__name__)

# Aggiornamenti consecutivi senza temperatura prima di avvisare l'utente
MISSING_TEMPERATURE_NOTIFY_AFTER = 3


async def async_setup_entry(
    hass, config_entry, async_add_entities: AddEntitiesCallback
):
    """Set up climate platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    envID = coordinator.envID

    # I radiatori arrivano dal GetShadow già fatto dal coordinator
    radiators = extract_device_info(coordinator.desired)
    _LOGGER.debug(f"Retrieved radiators: {[r['serial'] for r in radiators]}")

    entities = []
    for r in radiators:
        device = RadiatorDevice(r, envID)
        device_manager.add_device(device)  # Aggiungi il dispositivo al manager
        entities.append(
            RadiatorClimate(coordinator, r, envID, unique_id=f"{r['serial']}_climate")
        )
    async_add_entities(entities)


def extract_device_info(
    payload,
    nam_suffix="_NAM",
    tmp_suffix="_TMP",
    enb_suffix="_ENB",
    srl_suffix="_SRL",
    exclude_suffix="E_NAM",
):
    devices_info = []

    # Suffixi di interesse per le chiavi
    suffixes = [
        "_SRL",
        "_FWV",
        "_TYP",
        "_X_ipAddress",
    ]

    # Trova tutte le chiavi _NAM, _SRL, _FWV, _TYP e _X_ipAddress in ordine
    nam_keys = []
    srl_keys = []
    fwv_keys = []
    typ_keys = []
    ip_keys = []

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

                # Trova chiavi _SRL, _FWV, _TYP, _X_ipAddress e aggiungile agli elenchi
                if any(key.endswith(suffix) for suffix in suffixes):
                    if key.endswith("_SRL"):
                        srl_keys.append((key, value))
                    elif key.endswith("_FWV"):
                        fwv_keys.append((key, value))
                    elif key.endswith("_TYP"):
                        typ_keys.append((key, value))
                    elif key.endswith("_X_ipAddress"):
                        ip_keys.append((key, value))

                # Ricorsione per trovare chiavi nested
                find_device_keys(value)
        elif isinstance(obj, list):
            for item in obj:
                find_device_keys(item)

    # Esegui la ricerca di chiavi nel payload
    find_device_keys(payload)

    # Associa ogni _NAM ai suoi corrispondenti attributi in ordine di apparizione
    for i, (nam_key, device_info) in enumerate(nam_keys):
        base_key = nam_key[: -len(nam_suffix)]
        corresponding_tmp_key = base_key + tmp_suffix
        corresponding_enb_key = base_key + enb_suffix

        # Trova la temperatura
        if corresponding_tmp_key in payload:
            tmp_value = payload[corresponding_tmp_key]
            device_info["temperature"] = (
                float(tmp_value) / 10 if tmp_value is not None else 0
            )

        # Trova lo stato (ON/OFF)
        if corresponding_enb_key in payload:
            enb_value = payload[corresponding_enb_key]
            device_info["state"] = "HEAT" if enb_value == 1 else "OFF"

        # Associa SRL, FWV, TYP e IP in base alla posizione dell'indice
        if i < len(srl_keys):
            device_info["mac"] = srl_keys[i][1]
        if i < len(fwv_keys):
            device_info["firmware"] = fwv_keys[i][1]
        if i < len(typ_keys):
            device_info["model"] = typ_keys[i][1]
        if i < len(ip_keys):
            device_info["ip_address"] = ip_keys[i][1]

        devices_info.append(device_info)

    return devices_info


def find_device_key_by_name(payload, device_name, nam_suffix="_NAM"):
    "Trova la chiave del dispositivo in base al nome."
    for key, value in payload.items():
        if key.endswith(nam_suffix) and value == device_name:
            return key[
                : -len(nam_suffix)
            ]  # Restituisce il prefisso del dispositivo (es. 'PCM', 'PTO')
    return None


class RadiatorClimate(CoordinatorEntity, ClimateEntity):
    "Representation of a radiator climate entity."

    def __init__(self, coordinator, radiator, envID, unique_id):
        super().__init__(coordinator)
        self._radiator = radiator
        self._device = RadiatorDevice(radiator, envID)
        self._attr_name = f"{radiator['serial']} Radiator"
        self._attr_unique_id = unique_id
        self._current_temperature = radiator.get("temperature", 0)
        self._target_temperature = 18.0  # Imposta una temperatura target predefinita
        self._state = radiator["state"]  # Usa il valore di _ENB per lo stato
        self._envID = envID
        # Dopo un comando lo shadow nel cloud può essere ancora quello vecchio:
        # fino a questo istante gli aggiornamenti del coordinator vengono ignorati
        self._ignore_updates_until = 0.0
        self._missing_temperature_count = 0
        self._serial_number = radiator.get("mac")
        self._sw_version = radiator.get("firmware")
        self._model = radiator.get("model")

        # Modalità HVAC supportate (HEAT, OFF)
        self._attr_hvac_modes = [
            HVACMode.HEAT,
            HVACMode.OFF,
        ]  # Usa HVACMode per le modalità

        # Imposta la modalità HVAC in base allo stato corrente
        if self._state == "HEAT":
            self._attr_hvac_mode = HVACMode.HEAT
        elif self._state == "OFF":
            self._attr_hvac_mode = HVACMode.OFF
        else:
            self._attr_hvac_mode = (
                HVACMode.OFF
            )  # Fallback in caso di valori non riconosciuti

        # Funzionalità supportate (es. temperatura target e accensione/spegnimento)
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

        _LOGGER.debug(
            f"Initialized {self._attr_name} with state {self._attr_hvac_mode}"
        )

    @property
    def min_temp(self):
        "Restituisce la temperatura minima raggiungibile."
        return 12  # Temperatura minima di 12 gradi

    @property
    def max_temp(self):
        "Restituisce la temperatura massima raggiungibile."
        return 32  # Temperatura massima di 32 gradi

    @property
    def name(self):
        "Return the name of the climate device."
        return self._attr_name

    @property
    def unique_id(self):
        "Return a unique ID for the climate device."
        return self._attr_unique_id

    @property
    def temperature_unit(self):
        "Return the unit of measurement."
        return UnitOfTemperature.CELSIUS  # Usa UnitOfTemperature

    @property
    def current_temperature(self):
        "Return the current temperature."
        return self._current_temperature

    @property
    def target_temperature(self):
        "Return the target temperature."
        return self._target_temperature

    @property
    def hvac_mode(self):
        "Return current HVAC mode."
        return self._attr_hvac_mode

    @property
    def hvac_modes(self):
        "Return available HVAC modes."
        return self._attr_hvac_modes

    @property
    def extra_state_attributes(self):
        """Return additional attributes like IP address."""
        return {
            "min_temperature": self._radiator.get("min_temperature"),
            "max_temperature": self._radiator.get("max_temperature"),
        }

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {
                (DOMAIN, self._device.radiator["serial"])
            },  # Use device serial number
            "name": self._device.radiator["serial"],
            "model": self._device.radiator.get("model", "Unknown model"),
            "manufacturer": "IRSAP",
            "sw_version": self._device.radiator.get("firmware", "unknown"),
        }

    # Funzione per inviare il payload aggiornato alle API
    async def _send_target_temperature_to_api(self, token, envID, updated_payload):
        "Invia il payload aggiornato alle API."
        return await async_update_shadow(self.hass, token, envID, updated_payload)

    async def find_device_key_by_name(payload, device_name, nam_suffix="_NAM"):
        "Trova la chiave del dispositivo in base al nome."
        for key, value in payload.items():
            if key.endswith(nam_suffix) and value == device_name:
                return key[
                    : -len(nam_suffix)
                ]  # Restituisci il prefisso (es. 'PCM', 'PTO')
        return None

    async def generate_device_payload(
        self, payload, device_name, temperature=None, enable=None
    ):
        # Aggiorna il timestamp con il tempo attuale in millisecondi
        current_timestamp = int(time.time() * 1000)  # Tempo attuale in millisecondi
        payload["timestamp"] = current_timestamp  # Aggiorna il timestamp nel payload

        payload["clientId"] = (
            "app-now2-1.9.38-2143-ios-bdd093f2-8e08-4541-8a7e-800c23274f21"  # Fake clientId iOS
        )

        # "Aggiorna il payload del dispositivo con una nuova temperatura o stato di accensione/spegnimento"
        desired_payload = payload.get("state", {}).get(
            "desired", {}
        )  # Accedi a payload["state"]["desired"]

        timestamp_24h_future = int(time.time()) + 24 * 3600
        time_24h_future = time.strftime(
            "%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(timestamp_24h_future)
        )

        # Controlla la pianificazione `E_SCH` per ciascun radiatore
        num_radiatori = sum(1 for key in desired_payload if key.endswith("_NAM"))
        has_scheduling = len(desired_payload.get("E_SCH", [])) == num_radiatori

        # Cerca il device nel payload basato sul nome
        for key, value in desired_payload.items():
            if key.endswith("_NAM") and value == device_name:
                base_key = key[:-4]  # Ottieni la chiave di base senza il suffisso

                # Aggiorna la temperatura se fornita
                if temperature is not None:
                    # Aggiorna _MSP
                    msp_key = f"{base_key}_MSP"
                    if msp_key in desired_payload:
                        if "p" in desired_payload[msp_key]:
                            desired_payload[msp_key]["p"]["v"] = int(temperature * 10)

                    tsp_key = f"{base_key}_TSP"
                    if tsp_key in desired_payload:
                        desired_payload[tsp_key] = {
                            "p": {
                                "u": 0,
                                "v": int(temperature * 10),
                                "m": 3,
                                "k": "TEMPORARY",
                            },
                            "e": time_24h_future
                            if has_scheduling
                            else "1970-01-01T00:00:00.000Z",
                        }

                    # Imposta _MOD in base alla logica definita sopra
                    mod_key = f"{base_key}_MOD"
                    desired_payload[mod_key] = 2 if has_scheduling else 1

                    # Aggiorna _CSP
                    csp_key = f"{base_key}_CSP"
                    if csp_key in desired_payload:
                        if "p" in desired_payload[csp_key]:
                            desired_payload[csp_key]["p"]["v"] = int(temperature * 10)

                    # Aggiorna E_CLL se presente, impostandolo a 1
                    ecll_key = "E_CLL"
                    if ecll_key in desired_payload:
                        desired_payload[ecll_key] = 1  # Imposta E_CLL a 1

                    # Aggiorna E_CPC se presente, impostandolo a 1
                    ecpc_key = "E_CPC"
                    if ecpc_key in desired_payload:
                        desired_payload[ecpc_key] = 1  # Imposta E_CPC a 1

                    break

        # Rimuovi 'sk' se esistente
        desired_payload.pop("sk", None)

        # Aggiorna il payload originale
        payload["state"]["desired"] = desired_payload

        # Riordina il payload secondo l'ordine richiesto
        ordered_payload = {
            "id": payload.get("id"),
            "clientId": payload.get("clientId"),
            "timestamp": payload.get("timestamp"),
            "version": payload.get("version"),
            "state": payload["state"],
        }

        return ordered_payload  # Restituisci il payload aggiornato

    async def generate_state_payload(self, payload, device_name, enable):
        "Aggiorna il payload del dispositivo solo per lo stato di accensione/spegnimento."
        current_timestamp = int(time.time() * 1000)  # Tempo attuale in millisecondi
        payload["timestamp"] = current_timestamp  # Aggiorna il timestamp nel payload

        desired_payload = payload.get("state", {}).get(
            "desired", {}
        )  # Accedi a payload["state"]["desired"]

        # Cerca il device nel payload basato sul nome
        for key, value in desired_payload.items():
            if key.endswith("_NAM") and value == device_name:
                base_key = key[:-4]  # Ottieni la chiave di base senza il suffisso

                # Aggiorna lo stato di accensione/spegnimento se fornito
                enable_key = f"{base_key}_ENB"
                if enable_key in desired_payload:
                    desired_payload[enable_key] = enable  # Imposta a 1 (on) o 0 (off)

                # Aggiorna _CLL se presente, impostandolo a 1
                cll_key = f"{base_key}_CLL"
                if cll_key in desired_payload:
                    desired_payload[cll_key] = 1  # Imposta _CLL a 1

                break

        # Rimuovi 'sk' se esistente
        desired_payload.pop("sk", None)

        # Aggiorna il payload originale
        payload["state"]["desired"] = desired_payload

        # Riordina il payload secondo l'ordine richiesto
        ordered_payload = {
            "id": payload.get("id"),
            "clientId": payload.get("clientId"),
            "timestamp": payload.get("timestamp"),
            "version": payload.get("version"),
            "state": payload.get("state"),
        }

        return ordered_payload  # Restituisci il payload aggiornato

    async def generate_device_payload_for_hvac(
        self, payload, device_name, hvac_mode=None, enable=None
    ):
        # Aggiorna il timestamp con il tempo attuale in millisecondi
        current_timestamp = int(time.time() * 1000)  # Tempo attuale in millisecondi
        payload["timestamp"] = current_timestamp  # Aggiorna il timestamp nel payload

        payload["clientId"] = (
            "app-now2-1.9.38-2143-ios-bdd093f2-8e08-4541-8a7e-800c23274f21"  # Aggiorna il clientId facendo finta di essere l'App su iOS
        )

        # "Aggiorna il payload del dispositivo con una nuova temperatura o stato di accensione/spegnimento"
        desired_payload = payload.get("state", {}).get(
            "desired", {}
        )  # Accedi a payload["state"]["desired"]

        # Trova il dispositivo specifico e aggiorna solo quello
        device_found = False
        for key, value in desired_payload.items():
            if key.endswith("_NAM") and value == device_name:
                base_key = key[:-4]  # Ottieni la chiave di base senza il suffisso

                if hvac_mode is not None:
                    enable_key = f"{base_key}_ENB"
                    if enable_key in desired_payload:
                        # Set the value based on the hvac_mode
                        desired_payload[enable_key] = 1 if hvac_mode == 1 else 0
                device_found = True
                break  # Esci dal ciclo una volta trovato e aggiornato il dispositivo

        # Se il dispositivo non è stato trovato, non fare nulla
        if not device_found:
            return payload  # Restituisci il payload invariato

        # Rimuovi 'sk' se esistente
        desired_payload.pop("sk", None)

        # Aggiorna il payload originale
        payload["state"]["desired"] = desired_payload

        # Riordina il payload secondo l'ordine richiesto
        ordered_payload = {
            "id": payload.get("id"),
            "clientId": payload.get("clientId"),
            "timestamp": payload.get("timestamp"),
            "version": payload.get("version"),
            "state": payload.get("state"),
        }

        # Serializza il payload in JSON per garantire che None sia convertito in null
        json_payload_str = json.dumps(ordered_payload)
        # Deserializza il JSON per ottenere il payload nel formato corretto
        final_payload = json.loads(json_payload_str)

        return final_payload

    async def async_set_temperature(self, **kwargs):
        await asyncio.sleep(1)

        "Imposta la temperatura target del radiatore."
        temperature = kwargs.get("temperature")  # Estrae la temperatura dai kwargs

        # Token in cache; se il GetShadow fallisce ne viene chiesto uno nuovo
        token, payload = await async_fetch_shadow(self.hass, self._envID)

        if payload is None:
            _LOGGER.error(
                f"Failed to retrieve payload after token regeneration for {self._attr_name}"
            )
            return

        # Aggiorna il payload con la nuova temperatura
        updated_payload = await self.generate_device_payload(
            payload=payload,
            device_name=self._attr_name.replace("Radiator", "").strip(),
            temperature=temperature,  # Passa la temperatura come keyword argument
        )

        # Invia il nuovo payload aggiornato alle API
        success = await self._send_target_temperature_to_api(
            token, self._envID, updated_payload
        )
        if success:
            self._target_temperature = temperature
            # Cambia lo stato in HEAT
            self._attr_hvac_mode = HVACMode.HEAT
            self._ignore_updates_until = time.monotonic() + WRITE_SETTLE_TIME
            self.async_write_ha_state()
        else:
            _LOGGER.error(f"Failed to update temperature for {self._attr_name}")

    async def async_set_hvac_mode(self, hvac_mode):
        if self._attr_hvac_mode == hvac_mode:
            _LOGGER.debug(
                f"HVAC mode for {self._attr_name} is already {hvac_mode}, skipping update"
            )
            return
        if hvac_mode not in (HVACMode.OFF, HVACMode.HEAT):
            _LOGGER.error(f"Unsupported HVAC mode: {hvac_mode}")
            return
        await asyncio.sleep(1)
        "Set new target HVAC mode."
        _LOGGER.debug(f"Setting {self._radiator['serial']} to {hvac_mode}")

        # Ottieni il payload attuale del dispositivo dalle API (token in cache)
        token, payload = await async_fetch_shadow(self.hass, self._envID)

        if payload is None:
            _LOGGER.error(f"Failed to retrieve current payload for {self._attr_name}")
            return

        # Aggiorna il payload con la nuova modalità
        updated_payload = await self.generate_device_payload_for_hvac(
            payload=payload,
            device_name=self._attr_name.replace("Radiator", "").strip(),
            hvac_mode=1 if hvac_mode == HVACMode.HEAT else 0,
        )

        # Invia il nuovo payload aggiornato alle API
        success = await self._send_target_temperature_to_api(
            token, self._envID, updated_payload
        )

        if success:
            # Aggiorna la modalità HVAC attuale
            self._attr_hvac_mode = hvac_mode
            self._ignore_updates_until = time.monotonic() + WRITE_SETTLE_TIME
            self.async_write_ha_state()
        else:
            _LOGGER.error(f"Failed to update HVAC mode for {self._attr_name}")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Stato iniziale dai dati già scaricati dal coordinator
        self._update_from_payload(self.coordinator.desired)

    @callback
    def _handle_coordinator_update(self) -> None:
        if time.monotonic() < self._ignore_updates_until:
            # Evita di sovrascrivere il valore appena impostato con uno shadow vecchio
            _LOGGER.debug(f"Ignoring update for {self._attr_name} right after a command")
            return
        self._update_from_payload(self.coordinator.desired)
        self.async_write_ha_state()

    def _update_from_payload(self, desired_payload):
        "Aggiorna temperatura e modalità dal payload del coordinator."
        _LOGGER.debug(f"Updating radiator climate {self._attr_name}")

        # Rimuove "Radiator" dal nome dell'entità, se presente, per facilitare il matching
        device_name = self._attr_name.replace("Radiator", "").strip()

        enb_key = None
        tmp_value = None

        for key, value in desired_payload.items():
            if key.endswith("_NAM") and value == device_name:
                base_key = key[:-4]  # Ottieni la chiave base
                tmp_key = f"{base_key}_TMP"
                msp_key = f"{base_key}_MSP"
                enb_key = f"{base_key}_ENB"

                # Ottieni la temperatura
                tmp_value = desired_payload.get(tmp_key, None)
                if tmp_value is not None:
                    self._current_temperature = tmp_value / 10

                # Ottieni la temperatura target
                msp_value = desired_payload.get(msp_key)
                if isinstance(msp_value, dict):
                    target = msp_value.get("p", {}).get("v")
                    if target is not None:
                        self._target_temperature = target / 10

        # Se la temperatura manca per più aggiornamenti di fila, avvisa l'utente
        # (resta l'ultima temperatura valida)
        notification_id = f"radiator_{self._attr_name}_temperature_warning"
        if tmp_value is None:
            self._missing_temperature_count += 1
            _LOGGER.debug(
                f"Temperature is None for {self._attr_name} "
                f"({self._missing_temperature_count} updates in a row)"
            )
            if self._missing_temperature_count >= MISSING_TEMPERATURE_NOTIFY_AFTER:
                persistent_notification.async_create(
                    self.hass,
                    "Temperature is set to previous state due to an invalid value received (None). Please check the device and try to reset it.",
                    title=f"Device {self._attr_name} Issue",
                    notification_id=notification_id,
                )
        else:
            if self._missing_temperature_count >= MISSING_TEMPERATURE_NOTIFY_AFTER:
                persistent_notification.async_dismiss(self.hass, notification_id)
            self._missing_temperature_count = 0

        # Controlla e aggiorna modalità di funzionamento (es. HEAT, OFF)
        if enb_key is not None and enb_key in desired_payload:
            enb_value = desired_payload.get(enb_key, 0)
            self._attr_hvac_mode = HVACMode.HEAT if enb_value == 1 else HVACMode.OFF

        _LOGGER.debug(
            f"Final state for {self._attr_name}: Temperature={self._current_temperature}, HVAC mode={self._attr_hvac_mode}"
        )
