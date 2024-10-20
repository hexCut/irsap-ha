import sys
import os
import pytest

# Aggiungi la directory 'irsap-ha' al PYTHONPATH
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'irsap-ha')))

# Ora puoi importare i moduli dal pacchetto irsap-ha
from climate import RadiatorClimate
from homeassistant.components.climate.const import HVAC_MODE_HEAT, HVAC_MODE_OFF

@pytest.fixture
def climate_entity():
    """Fixture per creare una nuova entità Climate."""
    return RadiatorClimate(hass=None, name="Test Climate")

def test_initial_state(climate_entity):
    """Test dell'inizializzazione dell'entità."""
    assert climate_entity.hvac_mode == HVAC_MODE_OFF
    assert climate_entity.target_temperature == 20

def test_set_hvac_mode(climate_entity):
    """Test della modifica della modalità HVAC."""
    climate_entity.set_hvac_mode(HVAC_MODE_HEAT)
    assert climate_entity.hvac_mode == HVAC_MODE_HEAT

def test_set_temperature(climate_entity):
    """Test dell'impostazione della temperatura."""
    climate_entity.set_temperature(temperature=25)
    assert climate_entity.target_temperature == 25
