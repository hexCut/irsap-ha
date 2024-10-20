import sys
import os
import pytest
from homeassistant import config_entries

# Aggiungi la directory 'irsap-ha' al PYTHONPATH
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'irsap-ha')))

# Importa il modulo config_flow e const dal pacchetto irsap-ha
from config_flow import ConfigFlow  # Assicurati che il nome della classe sia corretto
from const import DOMAIN  # Assicurati che il file const.py sia presente e correttamente importato

@pytest.fixture
def config_flow():
    """Fixture per il config flow."""
    return ConfigFlow()

async def test_show_form(hass, config_flow):
    """Test della visualizzazione del form di configurazione."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "user"

async def test_create_entry(hass, config_flow):
    """Test della creazione di una config entry."""
    result = await hass.config_entries.flow.async_configure(
        flow_id="test", user_input={"host": "192.168.1.1", "port": 8080}
    )
    assert result["type"] == "create_entry"
    assert result["data"]["host"] == "192.168.1.1"
    assert result["data"]["port"] == 8080
