# test_climate.py
import sys
import os
import pytest

# Add the 'custom_components' directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'custom_components')))

# Import the RadiatorClimate class using the correct path
from irsap-ha.climate import RadiatorClimate  # This should now work

@pytest.fixture
def radiator_climate():
    """Fixture to create a RadiatorClimate instance for testing."""
    return RadiatorClimate(name="Living Room Radiator", unique_id="unique_id_1")

def test_radiator_name(radiator_climate):
    """Test the name property of the RadiatorClimate instance."""
    assert radiator_climate.name == "Living Room Radiator"

def test_unique_id(radiator_climate):
    """Test the unique_id property of the RadiatorClimate instance."""
    assert radiator_climate.unique_id == "unique_id_1"
