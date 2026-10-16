import logging
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.data_entry_flow import FlowResult
import voluptuous as vol
from homeassistant.helpers import selector
from .const import (
    DOMAIN,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    MAX_SCAN_INTERVAL,
)
from .api import async_list_environments
from .auth import login_with_srp as _sync_login_with_srp

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    "Handle a config flow for radiators integration."

    VERSION = 1

    def __init__(self):
        # Credenziali e case dell'account tra il passo "user" e "environment"
        self._login = None
        self._environments = []

    async def async_step_user(self, user_input=None) -> FlowResult:
        "Handle the initial step."

        # Controlla se esiste già un'istanza dell'integrazione
        await self.async_set_unique_id(DOMAIN)
        existing_entry = self._async_current_entries()

        if existing_entry:
            # Se esiste già un'istanza, abortisci il flusso con un messaggio personalizzato
            return self.async_abort(reason="Only one istance is allowed")

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("username"): str,
                        vol.Required("password"): str,
                    }
                ),
            )

        # Estrazione delle credenziali dall'input dell'utente
        username = user_input["username"]
        password = user_input["password"]

        # Call the function directly since login_with_srp already handles executor wrapping
        token = await login_with_srp(self.hass, username, password)

        if token is None:
            _LOGGER.error("Login failed, invalid credentials.")
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("username"): str,
                        vol.Required("password"): str,
                    }
                ),
                errors={"base": "invalid_credentials"},
            )

        environments = await async_list_environments(self.hass, token)

        if not environments:
            _LOGGER.error("Failed to obtain envID.")
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("username"): str,
                        vol.Required("password"): str,
                    }
                ),
                errors={"base": "envid_failed"},
            )

        self._login = {"username": username, "password": password, "token": token}
        self._environments = environments
        if len(environments) == 1:
            return self._create_entry(environments[0])
        # Più case nello stesso account: si sceglie quale integrare
        return await self.async_step_environment()

    async def async_step_environment(self, user_input=None):
        "Sceglie la casa (environment IRSAP) da integrare."
        if user_input is not None:
            chosen = next(
                env
                for env in self._environments
                if env["envId"] == user_input["envID"]
            )
            return self._create_entry(chosen)

        return self.async_show_form(
            step_id="environment",
            data_schema=vol.Schema(
                {
                    vol.Required("envID"): vol.In(
                        {env["envId"]: env["envName"] for env in self._environments}
                    )
                }
            ),
        )

    def _create_entry(self, environment):
        username = self._login["username"]
        title = username
        if len(self._environments) > 1:
            title = f"{username} ({environment['envName']})"
        return self.async_create_entry(
            title=title,
            data={**self._login, "envID": environment["envId"]},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return RadiatorsIntegrationOptionsFlow()


class RadiatorsIntegrationOptionsFlow(config_entries.OptionsFlow):
    "Handle the options flow for the integration."

    # NB: self.config_entry is provided by Home Assistant (2024.11+); assigning
    # it in __init__ is deprecated and no longer works on recent versions.

    async def async_step_init(self, user_input=None):
        "Manage the options."
        errors = {}
        entry = self.config_entry

        if user_input is not None:
            username = user_input["username"]
            password = user_input["password"]

            # Credenziali modificate: verificale e salvale in entry.data, che è
            # dove le leggono le piattaforme
            if username != entry.data.get("username") or password != entry.data.get(
                "password"
            ):
                token = await login_with_srp(self.hass, username, password)
                if token is None:
                    errors["base"] = "invalid_credentials"
                else:
                    # Dati e opzioni in un solo aggiornamento, così l'integrazione
                    # si ricarica una volta sola
                    self.hass.config_entries.async_update_entry(
                        entry,
                        data={
                            **entry.data,
                            "username": username,
                            "password": password,
                            "token": token,
                        },
                        options={
                            CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])
                        },
                    )

            if not errors:
                # Nelle opzioni resta solo l'intervallo di aggiornamento;
                # il listener in __init__ ricarica l'integrazione
                return self.async_create_entry(
                    title="",
                    data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])},
                )

        options_schema = vol.Schema(
            {
                vol.Required("username", default=entry.data.get("username")): str,
                vol.Required("password", default=entry.data.get("password")): str,
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=entry.options.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=1,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="init", data_schema=options_schema, errors=errors
        )

    async def _update_options(self, user_input):
        "Update config entry options and reload entities."
        # Aggiorna le opzioni con le nuove credenziali
        self.hass.config_entries.async_update_entry(self.config_entry, data=user_input)

        # Ottieni il registro delle entità
        entity_registry = er.async_get(self.hass)

        # Elimina le entità esistenti create dall'integrazione
        entities = er.async_entries_for_config_entry(
            entity_registry, self.config_entry.entry_id
        )
        for entity in entities:
            entity_registry.async_remove(entity.entity_id)

        return self.async_create_entry(title="", data=user_input)


async def login_with_srp(hass, username, password):
    "Log in and obtain the access token using Warrant."
    return await hass.async_add_executor_job(_sync_login_with_srp, username, password)
