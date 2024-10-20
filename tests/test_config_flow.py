import pytest
from homeassistant import config_entries
from custom_component_name.config_flow import MyClimateConfigFlow
from custom_component_name.const import DOMAIN

@pytest.fixture
def config_flow():
    """Fixture per il config flow."""
    return MyClimateConfigFlow()

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
