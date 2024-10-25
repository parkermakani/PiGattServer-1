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
import signal
import sys

# Import mock D-Bus for development mode
if "REPL_ID" in os.environ:
    from mock_dbus import MockMessageBus
    logger.info("Using Mock D-Bus implementation for development")
else:
    logger.info("Using dbus-python implementation")

from service_definitions import ServiceDefinitions, CharacteristicProperties, GattService, GattCharacteristic

BLUEZ_SERVICE_NAME = 'org.bluez'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHRC_IFACE = 'org.bluez.GattCharacteristic1'
LE_ADVERTISEMENT_IFACE = 'org.bluez.LEAdvertisement1'

DBUS_SERVICE_NAME = 'org.bluez.pigattserver'
DBUS_BASE_PATH = '/org/bluez/pigattserver'

class BLEGATTServer:
    def __init__(self, bus, adapter_name):
        self.path = '/org/bluez/example/service'
        self.bus = bus
        self.adapter = adapter_name
        super().__init__(bus, self.path)

        self._setup_dbus()

    def _setup_dbus(self):
        """Initialize D-Bus interface and setup required services"""
        try:
            # Get the system bus
            self.bus = dbus.SystemBus()

            # Get the BLE controller
            adapter = self.bus.get_object('org.bluez', f'/org/bluez/{self.adapter}')
            adapter_props = dbus.Interface(adapter, 'org.freedesktop.DBus.Properties')

            # Power on the adapter if it's not already
            if not adapter_props.Get('org.bluez.Adapter1', 'Powered'):
                adapter_props.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(1))

            # Set up advertisement
            self.ad_manager = dbus.Interface(adapter, 'org.bluez.LEAdvertisingManager1')
            self.service_manager = dbus.Interface(adapter, 'org.bluez.GattManager1')

        except dbus.exceptions.DBusException as e:
            print(f"D-Bus setup failed: {str(e)}")
            raise

    def start(self):
        """Start the GATT server"""
        try:
            # Register GATT services
            self.service_manager.RegisterApplication(self.get_path(), {})
            print("GATT application registered")

            # Start advertising
            self.ad_manager.RegisterAdvertisement(self.get_path(), {})
            print("Advertisement registered")

        except dbus.exceptions.DBusException as e:
            print(f"Failed to start GATT server: {str(e)}")
            raise

    def stop(self):
        """Stop the GATT server"""
        try:
            self.ad_manager.UnregisterAdvertisement(self.get_path())
            self.service_manager.UnregisterApplication(self.get_path())
        except dbus.exceptions.DBusException as e:
            print(f"Failed to stop GATT server: {str(e)}")
    
    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals with proper cleanup coordination."""
        if self.shutdown_event.is_set():
            logger.info("Shutdown already in progress, waiting...")
            return

        logger.info(f"Received signal {signum}, initiating shutdown...")
        self.shutdown_event.set()

        # Start cleanup in a separate thread to avoid blocking
        cleanup_thread = threading.Thread(target=self._coordinated_cleanup)
        cleanup_thread.start()

        # Wait for cleanup with timeout
        cleanup_timeout = 30  # seconds
        if not self.cleanup_complete.wait(timeout=cleanup_timeout):
            logger.warning("Cleanup timeout reached, forcing exit")
        
        if self.mainloop and self.mainloop.is_running():
            self.mainloop.quit()

    def _coordinated_cleanup(self):
        """Perform cleanup in a coordinated manner."""
        with self.cleanup_lock:
            try:
                # Stop advertising first
                self._cleanup_advertisement()
                time.sleep(2)  # Allow time for advertisement cleanup

                # Unregister service
                self._cleanup_service()
                time.sleep(2)  # Allow time for service cleanup

                # Release D-Bus name
                if hasattr(self, 'dbus_service_name'):
                    logger.debug("Releasing D-Bus service name")
                    del self.dbus_service_name

                # Final cleanup steps
                if self.mainloop and self.mainloop.is_running():
                    logger.debug("Quitting main loop")
                    GLib.idle_add(self.mainloop.quit)

                logger.info("Cleanup completed successfully")
            except Exception as e:
                logger.error(f"Error during coordinated cleanup: {str(e)}")
            finally:
                self.cleanup_complete.set()
                logger.info("GATT server stopped")

    def _cleanup_advertisement(self):
        """Clean up advertisement with retries."""
        if not hasattr(self, 'ad_manager') or not self.advertisement:
            return

        max_retries = 3
        retry_delay = 2

        for attempt in range(max_retries):
            try:
                logger.info(f"Unregistering advertisement at {self.advertisement.get_path()}")
                self.ad_manager.UnregisterAdvertisement(self.advertisement.get_path())
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Failed to unregister advertisement (attempt {attempt + 1}): {str(e)}")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Failed to unregister advertisement after {max_retries} attempts: {str(e)}")

    def _cleanup_service(self):
        """Clean up service with retries."""
        try:
            self._cleanup_advertisement()

            if hasattr(self, 'gatt_manager'):
                app_path = dbus.ObjectPath(DBUS_BASE_PATH)
                max_retries = 3
                retry_delay = 2

                for attempt in range(max_retries):
                    try:
                        logger.info(f"Unregistering application at {app_path}")
                        self.gatt_manager.UnregisterApplication(app_path)
                        return
                    except Exception as e:
                        if attempt < max_retries - 1:
                            logger.warning(f"Failed to unregister application (attempt {attempt + 1}): {str(e)}")
                            time.sleep(retry_delay)
                        else:
                            logger.error(f"Failed to unregister application after {max_retries} attempts: {str(e)}")

        except Exception as e:
            logger.error(f"Error during service cleanup: {str(e)}")

    def cleanup(self):
        """Main cleanup method."""
        if self.shutdown_event.is_set():
            logger.info("Cleanup already in progress")
            return

        self.shutdown_event.set()
        self._coordinated_cleanup()

    # [Previous methods remain unchanged...]

if __name__ == "__main__":
    try:
        server = BLEGATTServer()
        server.run()
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        sys.exit(1)
