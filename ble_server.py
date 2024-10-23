import asyncio
from dbus_next.aio.message_bus import MessageBus
from dbus_next.service import ServiceInterface, method, signal, dbus_property
from dbus_next.constants import BusType
from dbus_next import Variant, DBusError
from service_definitions import ServiceDefinitions, CharacteristicProperties
from logger_config import logger
from utils import check_bluetooth_status
import os

class GattCharacteristic(ServiceInterface):
    def __init__(self, characteristic_config):
        super().__init__('org.bluez.GattCharacteristic1')
        self._uuid = characteristic_config['uuid']
        self._value = characteristic_config['initial_value']
        self._properties = characteristic_config['properties']

    @dbus_property()
    def UUID(self) -> 's':
        return self._uuid

    @dbus_property()
    def Value(self) -> 'ay':
        return self._value

    @Value.setter
    def Value(self, value: 'ay'):
        self._value = value

    @dbus_property()
    def Properties(self) -> 'as':
        return self._properties

class GattService(ServiceInterface):
    def __init__(self):
        super().__init__('org.bluez.GattService1')
        self._uuid = ServiceDefinitions.CUSTOM_SERVICE_UUID
        self._primary = True

    @dbus_property()
    def UUID(self) -> 's':
        return self._uuid

    @dbus_property()
    def Primary(self) -> 'b':
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
        if self.is_development:
            logger.info("Development mode: Simulating D-Bus setup")
            return

        try:
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
        if self.is_development:
            logger.info("Development mode: Simulating service registration")
            return

        try:
            # Create and export service
            service = GattService()
            self.bus.export('/org/bluez/example/service0', service)

            # Create and export characteristics
            characteristics = {
                'temperature': CharacteristicProperties.TEMPERATURE,
                'humidity': CharacteristicProperties.HUMIDITY,
                'status': CharacteristicProperties.STATUS
            }

            for i, (name, config) in enumerate(characteristics.items()):
                char = GattCharacteristic(config)
                path = f'/org/bluez/example/service0/char{i}'
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
            if self.is_development:
                logger.info("Development mode: Simulating BLE advertising")
                while True:
                    await asyncio.sleep(1)
            else:
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
            if self.adapter and not self.is_development:
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
