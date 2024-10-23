import asyncio
from logger_config import logger
from utils import check_bluetooth_status
import os
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

# Import mock D-Bus for development mode
if "REPL_ID" in os.environ:
    from mock_dbus import MockMessageBus
    logger.info("Using Mock D-Bus implementation for development")
else:
    logger.info("Using dbus-python implementation")

from service_definitions import ServiceDefinitions, CharacteristicProperties

class GattCharacteristic(dbus.service.Object if not "REPL_ID" in os.environ else object):
    def __init__(self, bus, path, characteristic_config):
        if not "REPL_ID" in os.environ:
            dbus.service.Object.__init__(self, bus, path)
        self._path = path
        self._bus = bus
        self._uuid = characteristic_config['uuid']
        self._value = characteristic_config['initial_value']
        self._properties = characteristic_config['properties']

    @property
    def path(self):
        return self._path

    @dbus.service.method("org.bluez.GattCharacteristic1",
                        in_signature='', out_signature='ay')
    def ReadValue(self):
        logger.info(f"Reading value from characteristic {self._uuid}")
        return self._value

    @dbus.service.method("org.bluez.GattCharacteristic1",
                        in_signature='ay', out_signature='')
    def WriteValue(self, value):
        logger.info(f"Writing value to characteristic {self._uuid}")
        self._value = bytes(value)

class GattService(dbus.service.Object if not "REPL_ID" in os.environ else object):
    def __init__(self, bus, path):
        if not "REPL_ID" in os.environ:
            dbus.service.Object.__init__(self, bus, path)
        self._path = path
        self._bus = bus
        self._uuid = ServiceDefinitions.CUSTOM_SERVICE_UUID
        self._characteristics = {}
        self._primary = True

    @property
    def path(self):
        return self._path

    def add_characteristic(self, characteristic):
        self._characteristics[characteristic.path] = characteristic

class BLEGattServer:
    def __init__(self):
        """Initialize BLE GATT Server."""
        self.mainloop = None
        self.bus = None
        self.adapter = None
        self.service = None
        self.characteristics = {}
        self.is_development = "REPL_ID" in os.environ

    def setup_dbus(self):
        """Setup D-Bus connection and get BlueZ interface."""
        try:
            if self.is_development:
                self.bus = MockMessageBus()
                self.adapter = self.bus.adapter
                logger.info("Mock D-Bus setup completed successfully")
            else:
                dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
                self.bus = dbus.SystemBus()
                self.adapter = dbus.Interface(
                    self.bus.get_object('org.bluez', '/org/bluez/hci0'),
                    'org.bluez.Adapter1'
                )
                logger.info("D-Bus setup completed successfully")
        except Exception as e:
            logger.error(f"Failed to setup D-Bus: {str(e)}")
            raise

    def register_service(self):
        """Register GATT service and characteristics."""
        try:
            service_path = '/org/bluez/example/service0'
            self.service = GattService(self.bus, service_path)

            characteristics = {
                'temperature': CharacteristicProperties.TEMPERATURE,
                'humidity': CharacteristicProperties.HUMIDITY,
                'status': CharacteristicProperties.STATUS
            }

            for i, (name, config) in enumerate(characteristics.items()):
                path = f'{service_path}/char{i}'
                char = GattCharacteristic(self.bus, path, config)
                self.service.add_characteristic(char)
                self.characteristics[name] = char
                logger.info(f"Registered characteristic: {name} at {path}")

            logger.info("Service and characteristics registered successfully")
        except Exception as e:
            logger.error(f"Failed to register service: {str(e)}")
            raise

    def start_advertising(self):
        """Start BLE advertising."""
        try:
            if not self.is_development:
                # Power on adapter
                self.adapter.Set('org.bluez.Adapter1', 'Powered', True)
                logger.info("Bluetooth adapter powered on")

                # Set discoverable and pairable properties
                self.adapter.Set('org.bluez.Adapter1', 'Discoverable', True)
                self.adapter.Set('org.bluez.Adapter1', 'Pairable', True)

            # Register service and characteristics
            self.register_service()
            logger.info("Started advertising GATT service")

            # Start the main loop
            self.mainloop = GLib.MainLoop()
            self.mainloop.run()

        except Exception as e:
            logger.error(f"Error in GATT server: {str(e)}")
            raise
        finally:
            if self.adapter and not self.is_development:
                try:
                    self.adapter.Set('org.bluez.Adapter1', 'Discoverable', False)
                    self.adapter.Set('org.bluez.Adapter1', 'Pairable', False)
                except:
                    pass
            logger.info("GATT server stopped")

    def update_characteristic(self, name, value):
        """Update characteristic value."""
        if name in self.characteristics:
            char = self.characteristics[name]
            char._value = value if isinstance(value, bytes) else bytes(value)
            logger.info(f"Updated {name} characteristic value: {value}")
        else:
            logger.error(f"Characteristic {name} not found")

def main():
    """Main function to run the GATT server."""
    if not check_bluetooth_status():
        logger.error("Bluetooth is not available or not enabled")
        return

    server = BLEGattServer()
    try:
        server.setup_dbus()
        server.start_advertising()
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
        if server.mainloop:
            server.mainloop.quit()
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")

if __name__ == "__main__":
    main()
