import logging

_LOGGER = logging.getLogger(__name__)


class DeviceManager:
    def __init__(self):
        self.devices = []

    def add_device(self, device):
        self.devices.append(device)
        _LOGGER.debug(f"Device added: {device.radiator['serial']}")

    def get_devices(self):
        return self.devices

    def clear(self):
        """Forget all devices (called when the config entry is unloaded)."""
        self.devices.clear()


# Singleton
device_manager = DeviceManager()
