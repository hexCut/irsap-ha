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


# Singleton
device_manager = DeviceManager()
