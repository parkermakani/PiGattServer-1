import asyncio
from logger_config import logger
from utils import check_bluetooth_status
import os

# Import real or mock D-Bus based on environment
if "REPL_ID" in os.environ:
    from mock_dbus import MockMessageBus
    logger.info("Using Mock D-Bus implementation for development")
    BusType = type('MockBusType', (), {'SYSTEM': None})
else:
    from dbus_next.aio.message_bus import MessageBus
    from dbus_next.service import ServiceInterface, method, signal, dbus_property
    from dbus_next.constants import BusType
    from dbus_next import Variant, DBusError

from service_definitions import ServiceDefinitions, CharacteristicProperties

class GattCharacteristic:
    def __init__(self, characteristic_config):
        self._uuid = characteristic_config['uuid']
        self._value = characteristic_config['initial_value']
        self._properties = characteristic_config['properties']

    @property
    def UUID(self):
        return self._uuid

    @property
    def Value(self):
        return self._value

    @Value.setter
    def Value(self, value):
        self._value = value

    @property
    def Properties(self):
        return self._properties

class GattService:
    def __init__(self):
        self._uuid = ServiceDefinitions.CUSTOM_SERVICE_UUID
        self._primary = True

    @property
    def UUID(self):
        return self._uuid

    @property
    def Primary(self):
        return self._primary

class BLEGattServer:
    def __init__(self):
        """Initialize BLE GATT Server."""
        self.bus = None
        self.adapter = None
        self.service = None
        self.characteristics = {}
        self.is_development = "REPL_ID" in os.environ

    async def setup_dbus(self):
        """Setup D-Bus connection and get BlueZ interface."""
        try:
            if self.is_development:
                self.bus = MockMessageBus()
                await self.bus.connect()
                self.adapter = self.bus.adapter
                logger.info("Mock D-Bus setup completed successfully")
            else:
                self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
                introspection = await self.bus.introspect('org.bluez', '/org/bluez')
                obj = self.bus.get_proxy_object('org.bluez', '/org/bluez', introspection)
                self.adapter = obj.get_interface('org.bluez.Adapter1')
                logger.info("D-Bus setup completed successfully")
        except Exception as e:
            logger.error(f"Failed to setup D-Bus: {str(e)}")
            raise

    async def register_service(self):
        """Register GATT service and characteristics."""
        try:
            service = GattService()
            if not self.is_development:
                self.bus.export('/org/bluez/example/service0', service)

            characteristics = {
                'temperature': CharacteristicProperties.TEMPERATURE,
                'humidity': CharacteristicProperties.HUMIDITY,
                'status': CharacteristicProperties.STATUS
            }

            for i, (name, config) in enumerate(characteristics.items()):
                char = GattCharacteristic(config)
                path = f'/org/bluez/example/service0/char{i}'
                if not self.is_development:
                    self.bus.export(path, char)
                self.characteristics[name] = char
                logger.info(f"Registered characteristic: {name} at {path}")

            logger.info("Service and characteristics registered successfully")
        except Exception as e:
            logger.error(f"Failed to register service: {str(e)}")
            raise

    async def start_advertising(self):
        """Start BLE advertising."""
        try:
            # Power on adapter
            await self.adapter.set_property('Powered', True)
            logger.info("Bluetooth adapter powered on")

            # Register service and characteristics
            await self.register_service()

            # Set discoverable and pairable properties
            await self.adapter.set_property('Discoverable', True)
            await self.adapter.set_property('Pairable', True)

            logger.info("Started advertising GATT service")

            while True:
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Error in GATT server: {str(e)}")
            raise
        finally:
            if self.adapter:
                try:
                    await self.adapter.set_property('Discoverable', False)
                    await self.adapter.set_property('Pairable', False)
                except:
                    pass
            logger.info("GATT server stopped")

    async def update_characteristic(self, name, value):
        """Update characteristic value."""
        if name in self.characteristics:
            char = self.characteristics[name]
            char.Value = value
            logger.info(f"Updated {name} characteristic value: {value}")
        else:
            logger.error(f"Characteristic {name} not found")

async def main():
    """Main function to run the GATT server."""
    if not check_bluetooth_status():
        logger.error("Bluetooth is not available or not enabled")
        return

    server = BLEGattServer()
    try:
        await server.setup_dbus()
        await server.start_advertising()
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
