import asyncio
from logger_config import logger
from utils import check_bluetooth_status
import os
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import time
import threading
import json
import subprocess
from functools import wraps

# Import mock D-Bus for development mode
if "REPL_ID" in os.environ:
    from mock_dbus import MockMessageBus
    logger.info("Using Mock D-Bus implementation for development")
else:
    logger.info("Using dbus-python implementation")

from service_definitions import ServiceDefinitions, CharacteristicProperties

class BLEGATTServer:
    def __init__(self):
        self.is_development = "REPL_ID" in os.environ
        self.mainloop = None
        self.bus = None
        self.service = None
        self._setup_dbus()

    def _setup_dbus(self):
        """Initialize D-Bus and BlueZ interfaces."""
        try:
            if self.is_development:
                self.bus = MockMessageBus()
                return True

            # Initialize D-Bus mainloop
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            self.bus = dbus.SystemBus()
            self.mainloop = GLib.MainLoop()

            # Initialize adapter
            self.adapter = dbus.Interface(
                self.bus.get_object('org.bluez', '/org/bluez/hci0'),
                'org.bluez.Adapter1'
            )
            
            # Reset adapter
            self.reset_adapter()
            logger.info("D-Bus setup completed successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to setup D-Bus: {str(e)}")
            return False

    def reset_adapter(self):
        """Reset Bluetooth adapter with retry mechanism."""
        if self.is_development:
            logger.info("Development mode: Simulating adapter reset")
            return True

        try:
            logger.info("Resetting Bluetooth adapter...")
            self.adapter.SetProperty('Powered', dbus.Boolean(0))
            time.sleep(1)
            self.adapter.SetProperty('Powered', dbus.Boolean(1))
            logger.info("Bluetooth adapter reset successfully")
            return True
        except dbus.exceptions.DBusException as e:
            if "Busy" in str(e):
                logger.info("Attempting force reset due to busy adapter")
                return self._force_reset_adapter()
            logger.error(f"Failed to reset adapter: {str(e)}")
            return False

    def _force_reset_adapter(self):
        """Force reset Bluetooth adapter by restarting services."""
        try:
            logger.info("Performing force reset of Bluetooth adapter")
            services = ['bluetooth', 'bluetooth-mesh', 'bluealsa']
            
            for service in services:
                subprocess.run(['systemctl', 'stop', service], check=False)
            
            time.sleep(2)
            
            for service in services:
                subprocess.run(['systemctl', 'restart', service], check=False)
            
            time.sleep(5)
            return self.reset_adapter()
            
        except Exception as e:
            logger.error(f"Failed to force reset adapter: {str(e)}")
            return False

    def register_service(self):
        """Register GATT service and characteristics with improved reliability."""
        try:
            if self.is_development:
                logger.info("Development mode: Simulating service registration")
                return True

            self.service = GattService(self.bus, 0, ServiceDefinitions.CUSTOM_SERVICE_UUID)

            characteristics = [
                ('temperature', CharacteristicProperties.TEMPERATURE),
                ('humidity', CharacteristicProperties.HUMIDITY),
                ('status', CharacteristicProperties.STATUS),
                ('new_char', CharacteristicProperties.NEW_CHARACTERISTIC)
            ]

            for idx, (name, props) in enumerate(characteristics):
                char = GattCharacteristic(
                    self.bus,
                    idx,
                    props['uuid'],
                    props['properties'],
                    self.service
                )
                self.service.add_characteristic(char)
                logger.info(f"Registered characteristic: {name} at {char.path}")

            # Register the service with BlueZ
            try:
                self.bus.export(self.service.path, self.service)
                logger.info("Service and characteristics registered successfully")
                return True
            except Exception as e:
                logger.error(f"Failed to register service: {str(e)}")
                self._cleanup_service()
                raise

        except Exception as e:
            logger.error(f"Error during service registration: {str(e)}")
            return False

    def _cleanup_service(self):
        """Clean up service registration."""
        try:
            if hasattr(self, 'service'):
                self.bus.unexport(self.service.path)
        except Exception as e:
            logger.error(f"Error during service cleanup: {str(e)}")

    def run(self):
        """Start the GATT server and run the main loop."""
        try:
            if not check_bluetooth_status():
                raise Exception("Bluetooth is not available")

            if not self.register_service():
                raise Exception("Failed to register service")

            if self.is_development:
                logger.info("Development mode: Running mock server")
                while True:
                    time.sleep(1)
            else:
                logger.info("Starting GATT server main loop")
                self.mainloop.run()

        except KeyboardInterrupt:
            logger.info("Server shutdown requested")
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
        finally:
            self.cleanup()

    def cleanup(self):
        """Perform cleanup operations."""
        try:
            logger.info("Performing adapter cleanup...")
            if not self.is_development:
                self._cleanup_service()
                if self.mainloop and self.mainloop.is_running():
                    self.mainloop.quit()
            logger.info("Cleanup completed successfully")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
        finally:
            logger.info("GATT server stopped")

if __name__ == "__main__":
    server = BLEGATTServer()
    server.run()
