import time
from .const import DOMAIN, WRITE_SETTLE_TIME
from .api import async_fetch_shadow, async_update_shadow
import logging
from homeassistant.components.light import LightEntity, ColorMode
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .device_manager import device_manager
import asyncio
import colorsys

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    devices = device_manager.get_devices()  # Ottieni i dispositivi dal manager
    _LOGGER.debug(f"Devices found: {[device.radiator['serial'] for device in devices]}")

    if not devices:
        _LOGGER.error(
            "No devices found. Please ensure that climate entities are set up correctly."
        )
        return

    # Ottieni i dati delle luci dal GetShadow già fatto dal coordinator
    radiators_lights = extract_device_info(coordinator.desired)
    _LOGGER.info(f"Radiators lights data: {radiators_lights}")

    # Crea entità light
    lights = []
    for key, radiator in radiators_lights:  # Itera sulle tuple (key, value)
        if (
            isinstance(radiator, dict) and "serial" in radiator
        ):  # Verifica che il valore sia valido
            unique_id = f"{radiator['serial']}"
            lights.append(
                RadiatorLight(
                    coordinator,
                    radiator,
                    unique_id,
                    unique_id=f"{radiator['serial']}_led",
                )
            )
        else:
            _LOGGER.warning(f"Skipping invalid radiator data for key {key}: {radiator}")

    async_add_entities(lights)




def extract_device_info(
    payload,
    nam_suffix="_NAM",
    led_suffix="_X_LED_MSP",  # Suffisso per luce
    led_existance="_X_LED_CSP",  # Suffisso per verificare se c'è il led
    led_enable_suffix="_X_LED_ENB",
    exclude_suffix="E_NAM",
):
    devices_info = []
    temp_devices = {}  # Memorizza temporaneamente i dispositivi in attesa di verifica del LED

    def find_device_keys(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                # Memorizza le chiavi _NAM per dispositivi potenziali
                if key.endswith(nam_suffix) and not key.startswith(exclude_suffix):
                    temp_devices[key] = {
                        "serial": value,
                        "state": False,  # Default a OFF
                        "color": {"h": 0, "s": 0, "v": 0},  # Default colore
                        "has_led": False,  # Flag per la verifica del LED
                    }

                # Verifica la presenza del LED
                if (
                    key.endswith(led_existance)
                    and key.replace(led_existance, nam_suffix) in temp_devices
                ):
                    temp_devices[key.replace(led_existance, nam_suffix)]["has_led"] = (
                        value is not None
                    )

                # Gestisci stato accensione LED
                if (
                    key.endswith(led_enable_suffix)
                    and key.replace(led_enable_suffix, nam_suffix) in temp_devices
                ):
                    temp_devices[key.replace(led_enable_suffix, nam_suffix)][
                        "state"
                    ] = value == 1

                # Gestisci colore LED
                if key.endswith(led_suffix) and isinstance(value, dict):
                    nam_key = key.replace(led_suffix, nam_suffix)
                    if nam_key in temp_devices:
                        led_data = value.get("p", {})
                        color_data = led_data.get("v", {})
                        temp_devices[nam_key]["color"] = {
                            "h": color_data.get("h", 0),
                            "s": color_data.get("s", 0),
                            "v": color_data.get("v", 0),
                        }

                # Ricorsione per chiavi annidate
                find_device_keys(value)
        elif isinstance(obj, list):
            for item in obj:
                find_device_keys(item)

    # Esegui la ricerca nel payload
    find_device_keys(payload)

    # Filtra i dispositivi che hanno il LED
    devices_info = [
        (key, device) for key, device in temp_devices.items() if device["has_led"]
    ]

    return devices_info


class RadiatorLight(CoordinatorEntity, LightEntity):
    "Representation of a radiator light entity."

    def __init__(self, coordinator, radiator, device, unique_id):
        super().__init__(coordinator)
        self._envID = coordinator.envID
        # Dopo un comando lo shadow nel cloud può essere ancora quello vecchio
        self._ignore_updates_until = 0.0
        self._radiator = radiator
        self._device = device  # Store device reference
        self._attr_name = f"{radiator['serial']} LED"
        self._attr_unique_id = unique_id
        self._attr_icon = "mdi:led-strip-variant"
        self._radiator_serial = radiator["serial"]
        self._model = radiator.get("model", "Modello Sconosciuto")
        self._attr_native_value = radiator.get("ip_address", "IP non disponibile")
        self._sw_version = radiator.get("firmware")
        self._attr_is_on = radiator.get("state", False)
        # Convertire h, s, v in RGBW
        h = radiator["color"]["h"]
        s = radiator["color"]["s"]
        v = radiator["color"]["v"]
        self._attr_rgbw_color = self.hsv_to_rgbw(h, s, v)
        self._attr_brightness = (radiator["color"]["v"] / 100) * 255
        self._attr_supported_color_modes = {ColorMode.RGBW}

    def hsv_to_rgbw(self, h, s, v):
        "Converte HSV in RGBW."
        h = h / 360.0
        s = s / 100.0
        v = v / 100.0

        r, g, b = colorsys.hsv_to_rgb(h, s, v)

        w = min(r, g, b)

        r = int((r - w) * 255)
        g = int((g - w) * 255)
        b = int((b - w) * 255)
        w = int(w * 255)

        return (r, g, b, w)

    def _convert_rgbw_to_hsv(self, rgbw):
        "Converte un colore RGBW in HSV."
        red, green, blue, white = rgbw

        # Rimuovi il contributo del bianco per ottenere il colore RGB puro
        red -= white
        green -= white
        blue -= white

        # Assicurati che i valori non vadano sotto zero
        red = max(0, red)
        green = max(0, green)
        blue = max(0, blue)

        # Normalizza i valori RGB in un range 0-1
        red_norm = red / 255.0
        green_norm = green / 255.0
        blue_norm = blue / 255.0

        # Calcola HSV utilizzando formule standard
        max_val = max(red_norm, green_norm, blue_norm)
        min_val = min(red_norm, green_norm, blue_norm)
        delta = max_val - min_val

        # Calcola Hue (tonalità)
        if delta == 0:
            hue = 0
        elif max_val == red_norm:
            hue = ((green_norm - blue_norm) / delta) % 6
        elif max_val == green_norm:
            hue = ((blue_norm - red_norm) / delta) + 2
        else:  # max_val == blue_norm
            hue = ((red_norm - green_norm) / delta) + 4
        hue = round(hue * 60)  # Converti in gradi
        if hue < 0:
            hue += 360

        # Calcola Saturazione
        saturation = 0 if max_val == 0 else (delta / max_val)
        saturation = round(saturation * 100)  # Scala su 0-100

        # Calcola Valore
        value = round(max_val * 100)  # Scala su 0-100

        return hue, saturation, value

    @property
    def native_value(self):
        return self._attr_native_value

    @property
    def unique_id(self):
        return self._attr_unique_id

    @property
    def device_info(self):
        "Associa il sensore al dispositivo climate con il seriale corrispondente."
        return {
            "identifiers": {
                (DOMAIN, self._radiator["serial"])
            },  # Use device serial number
            "name": f"{self._radiator['serial']}",
            "model": self._radiator.get("model", "Unknown Model"),
            "manufacturer": "IRSAP",
            "sw_version": self._radiator.get("firmware", "Unknown Firmware"),
        }

    @property
    def is_on(self):
        return self._attr_is_on

    @property
    def brightness(self):
        "Return the brightness of the light."
        return self._attr_brightness

    @property
    def rgbw_color(self):
        "Return the RGBW color of the light."
        return self._attr_rgbw_color

    @property
    def color_mode(self):
        "Return the color mode of the light."
        return ColorMode.RGBW

    @callback
    def _handle_coordinator_update(self) -> None:
        "Aggiorna lo stato della luce dal payload del coordinator."
        if time.monotonic() < self._ignore_updates_until:
            _LOGGER.debug(f"Ignoring update for {self._attr_name} right after a command")
            return
        _LOGGER.debug(f"Updating radiator light {self._attr_name}")
        device_name = self._attr_name.replace("LED", "").strip()
        if not self._extract_light_info(self.coordinator.desired, device_name):
            _LOGGER.warning(f"Light info is incomplete for {self._attr_name}")
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        await asyncio.sleep(1)
        "Turn on the light with the specified settings."
        _LOGGER.debug(f"Turning on {self._attr_name} with kwargs: {kwargs}")

        # Imposta la luminosità, se specificata, o utilizza quella attuale
        brightness = kwargs.get("brightness", self._attr_brightness)
        if brightness is not None:
            # Converti la luminosità da Home Assistant (0-255) a IRSAP (0-100)
            brightness_irsap = round((brightness / 255) * 100)
            self._attr_brightness = brightness

        # Imposta il colore RGBW, se specificato
        if "rgbw_color" in kwargs:
            rgbw = kwargs["rgbw_color"]
            self._attr_rgbw_color = rgbw
            hsv = self._convert_rgbw_to_hsv(rgbw)
            h, s, v = hsv

        else:
            # Usa i valori HSV esistenti per mantenere il colore corrente
            hsv = self._convert_rgbw_to_hsv(self._attr_rgbw_color)
            h, s, v = hsv

        envID = self._envID

        # Token in cache; se il GetShadow fallisce ne viene chiesto uno nuovo
        token, payload = await async_fetch_shadow(self.hass, envID)

        if payload is None:
            _LOGGER.error(
                f"Failed to retrieve payload after token regeneration for {self._attr_name}"
            )
            return

        # Genera il payload con la funzione generate_device_payload
        updated_payload = await self.generate_device_payload(
            payload=payload,
            device_name=self._attr_name.replace("LED", "").strip(),
            light_state=True,  # Stato della luce (accensione)
            color=(h, s, v),  # Passa i valori HSV
            brightness=brightness_irsap,  # Passa la luminosità in scala 0-100
        )

        # Invia il nuovo payload aggiornato alle API
        success = await self._send_light_status_to_api(token, envID, updated_payload)
        if success:
            # Aggiorna lo stato interno
            self._attr_is_on = True
            self._ignore_updates_until = time.monotonic() + WRITE_SETTLE_TIME
            self.async_write_ha_state()
        else:
            _LOGGER.error(
                f"Failed to update color and status as ON for {self._attr_name}"
            )

    async def async_turn_off(self, **kwargs):
        await asyncio.sleep(1)
        "Turn on the light with the specified settings."
        _LOGGER.debug(f"Turning off {self._attr_name} with kwargs: {kwargs}")

        # Allo spegnimento la luminosità inviata è 0; si ricorda quella richiesta
        brightness = kwargs.get("brightness", self._attr_brightness)
        if brightness is not None:
            self._attr_brightness = brightness

        # Imposta il colore RGBW, se specificato
        if "rgbw_color" in kwargs:
            rgbw = kwargs["rgbw_color"]
            self._attr_rgbw_color = rgbw
            hsv = self._convert_rgbw_to_hsv(rgbw)
            h, s, v = hsv

        else:
            # Usa i valori HSV esistenti per mantenere il colore corrente
            hsv = self._convert_rgbw_to_hsv(self._attr_rgbw_color)
            h, s, v = hsv

        envID = self._envID

        # Token in cache; se il GetShadow fallisce ne viene chiesto uno nuovo
        token, payload = await async_fetch_shadow(self.hass, envID)

        if payload is None:
            _LOGGER.error(
                f"Failed to retrieve payload after token regeneration for {self._attr_name}"
            )
            return

        # Genera il payload con la funzione generate_device_payload
        updated_payload = await self.generate_device_payload(
            payload=payload,
            device_name=self._attr_name.replace("LED", "").strip(),
            light_state=False,  # Stato della luce (accensione)
            color=(h, s, v),  # Passa i valori HSV
            brightness=0,  # Passa la luminosità in scala 0-100
        )

        # Invia il nuovo payload aggiornato alle API
        success = await self._send_light_status_to_api(token, envID, updated_payload)
        if success:
            # Aggiorna lo stato interno
            self._attr_is_on = False
            self._ignore_updates_until = time.monotonic() + WRITE_SETTLE_TIME
            self.async_write_ha_state()
        else:
            _LOGGER.error(
                f"Failed to update color and status as OFF for {self._attr_name}"
            )

    def _extract_light_info(self, desired_payload, device_name):
        "Estrae informazioni sulla luce dal payload."
        for key, value in desired_payload.items():
            if key.endswith("_NAM") and value == device_name:
                base_key = key[:-4]
                msp_key = f"{base_key}_X_LED_MSP"
                enb_key = f"{base_key}_X_LED_ENB"

                msp_value = desired_payload.get(msp_key)
                enb_value = desired_payload.get(enb_key)

                if msp_value and "p" in msp_value and "v" in msp_value["p"]:
                    hsv = msp_value["p"]["v"]
                    h, s, v = hsv.get("h", 0), hsv.get("s", 0), hsv.get("v", 0)
                    h = h / 360.0
                    s = s / 100.0
                    v = v / 100.0

                    r, g, b = colorsys.hsv_to_rgb(h, s, v)

                    w = min(r, g, b)

                    r = int((r - w) * 255)
                    g = int((g - w) * 255)
                    b = int((b - w) * 255)
                    w = int(w * 255)
                    self._attr_rgbw_color = (r, g, b, w)
                    self._attr_brightness = (hsv.get("v", 255) / 100) * 255
                    self._attr_is_on = enb_value == 1
                    return True
        return False

    async def generate_device_payload(
        self, payload, device_name, light_state=None, color=None, brightness=None
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

        # Cerca il device nel payload basato sul nome
        for key, value in desired_payload.items():
            if key.endswith("_NAM") and value == device_name:
                base_key = key[:-4]  # Ottieni la chiave di base senza il suffisso

                # Aggiorna la temperatura se fornita
                if light_state is not None:
                    # Aggiorna _MSP
                    led_enb_key = f"{base_key}_X_LED_ENB"
                    desired_payload[led_enb_key] = 1 if light_state else 0

                    led_msp_key = f"{base_key}_X_LED_MSP"
                    if led_msp_key in desired_payload:
                        desired_payload[led_msp_key] = {
                            "p": {
                                "u": 1,
                                "v": {"h": color[0], "s": color[1], "v": brightness},
                                "m": 4,
                            }
                        }

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

    # Funzione per inviare il payload aggiornato alle API
    async def _send_light_status_to_api(self, token, envID, updated_payload):
        "Invia il payload aggiornato alle API."
        return await async_update_shadow(self.hass, token, envID, updated_payload)
