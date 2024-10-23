import asyncio
from logger_config import logger
from utils import check_bluetooth_status
import os
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import time

# Import mock D-Bus for development mode
if "REPL_ID" in os.environ:
    from mock_dbus import MockMessageBus
    logger.info("Using Mock D-Bus implementation for development")
else:
    logger.info("Using dbus-python implementation")

from service_definitions import ServiceDefinitions, CharacteristicProperties

class GattCharacteristic(dbus.service.Object if not "REPL_ID" in os.environ else object):
    """
    GATT characteristic implementation with proper D-Bus method signatures.
    """
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

    @dbus.service.method(dbus_interface='org.bluez.GattCharacteristic1',
                        in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        """Read characteristic value with proper D-Bus signature."""
        logger.info(f"Reading value from characteristic {self._uuid}")
        return dbus.Array(self._value, signature='y')

    @dbus.service.method(dbus_interface='org.bluez.GattCharacteristic1',
                        in_signature='aya{sv}', out_signature='')
    def WriteValue(self, value, options):
        """Write characteristic value with proper D-Bus signature."""
        logger.info(f"Writing value to characteristic {self._uuid}")
        self._value = bytes(value)

class GattService(dbus.service.Object if not "REPL_ID" in os.environ else object):
    """
    GATT service implementation with proper D-Bus interface.
    """
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
        self.adapter_interface = 'org.bluez.Adapter1'
        self.adapter_path = '/org/bluez/hci0'
        self._cleanup_required = False

    def reset_adapter(self):
        """Reset the Bluetooth adapter."""
        try:
            if self.is_development:
                logger.info("Development mode: Simulating adapter reset")
                return True

            if not self.adapter or not self.adapter_props:
                logger.error("Adapter not initialized")
                return False

            # Power cycle the adapter
            logger.info("Resetting Bluetooth adapter...")
            self.adapter_props.Set(self.adapter_interface, 'Powered', dbus.Boolean(False))
            time.sleep(1)  # Wait for adapter to power down
            self.adapter_props.Set(self.adapter_interface, 'Powered', dbus.Boolean(True))
            time.sleep(1)  # Wait for adapter to power up

            # Reset discoverable and pairable states
            self.adapter_props.Set(self.adapter_interface, 'Discoverable', dbus.Boolean(False))
            self.adapter_props.Set(self.adapter_interface, 'Pairable', dbus.Boolean(False))

            logger.info("Bluetooth adapter reset successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to reset adapter: {str(e)}")
            return False

    def cleanup(self):
        """Perform cleanup operations."""
        try:
            if not self.is_development and self._cleanup_required:
                logger.info("Performing adapter cleanup...")
                
                if self.adapter and self.adapter_props:
                    # Disable advertising
                    try:
                        self.adapter_props.Set(self.adapter_interface, 'Discoverable', dbus.Boolean(False))
                        self.adapter_props.Set(self.adapter_interface, 'Pairable', dbus.Boolean(False))
                    except Exception as e:
                        logger.warning(f"Error disabling advertising: {str(e)}")

                    # Power down adapter
                    try:
                        self.adapter_props.Set(self.adapter_interface, 'Powered', dbus.Boolean(False))
                    except Exception as e:
                        logger.warning(f"Error powering down adapter: {str(e)}")

                # Clear characteristics
                self.characteristics.clear()
                
                logger.info("Cleanup completed successfully")
            else:
                logger.info("Development mode: Skipping cleanup")

        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
        finally:
            self._cleanup_required = False

    def setup_dbus(self):
        """Setup D-Bus connection and get BlueZ interface with proper method signatures."""
        try:
            if self.is_development:
                self.bus = MockMessageBus()
                self.adapter = self.bus.adapter
                logger.info("Mock D-Bus setup completed successfully")
            else:
                dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
                self.bus = dbus.SystemBus()
                adapter_obj = self.bus.get_object('org.bluez', self.adapter_path)
                self.adapter = dbus.Interface(adapter_obj, self.adapter_interface)
                self.adapter_props = dbus.Interface(adapter_obj, 'org.freedesktop.DBus.Properties')
                
                # Reset adapter on startup
                if not self.reset_adapter():
                    raise Exception("Failed to reset adapter during setup")
                    
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
            self._cleanup_required = True
        except Exception as e:
            logger.error(f"Failed to register service: {str(e)}")
            raise

    def start_advertising(self):
        """Start BLE advertising with proper D-Bus property handling."""
        try:
            if not self.is_development:
                # Power on adapter using proper D-Bus property interface
                self.adapter_props.Set(self.adapter_interface, 'Powered', dbus.Boolean(True))
                logger.info("Bluetooth adapter powered on")

                # Set discoverable and pairable properties
                self.adapter_props.Set(self.adapter_interface, 'Discoverable', dbus.Boolean(True))
                self.adapter_props.Set(self.adapter_interface, 'Pairable', dbus.Boolean(True))

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
            self.cleanup()
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
    finally:
        if server:
            server.cleanup()

if __name__ == "__main__":
    main()
