"""Mock D-Bus interface for development mode."""
from logger_config import logger

class MockDBusInterface:
    def __init__(self):
        self.properties = {}
        logger.info("Initialized Mock D-Bus Interface")

    async def set_property(self, name, value):
        self.properties[name] = value
        logger.info(f"Mock: Set property {name} to {value}")
        return True

    def get_property(self, name):
        return self.properties.get(name)

class MockMessageBus:
    def __init__(self):
        self.objects = {}
        self.adapter = MockDBusInterface()
        logger.info("Initialized Mock Message Bus")

    async def connect(self):
        logger.info("Mock: Connected to D-Bus")
        return self

    def export(self, path, interface):
        self.objects[path] = interface
        logger.info(f"Mock: Exported interface at {path}")

    def get_proxy_object(self, *args):
        return self

    def get_interface(self, interface_name):
        if interface_name == 'org.bluez.Adapter1':
            return self.adapter
        return None
