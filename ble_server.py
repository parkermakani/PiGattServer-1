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
from functools import wraps
import json

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
        self.adapter = None
        self.adapter_props = None
        self.adapter_interface = 'org.bluez.Adapter1'
        self.status_update_thread = None
        self.running = False

    def setup_dbus(self):
        """Initialize D-Bus connection and get Bluetooth adapter."""
        try:
            if self.is_development:
                return True

            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            self.bus = dbus.SystemBus()
            self.adapter = self.bus.get_object('org.bluez', '/org/bluez/hci0')
            self.adapter_props = dbus.Interface(self.adapter, 'org.freedesktop.DBus.Properties')
            
            return True
        except Exception as e:
            logger.error(f"Failed to setup D-Bus: {str(e)}")
            return False

    def reset_adapter(self):
        """Reset Bluetooth adapter."""
        try:
            if self.is_development:
                logger.info("Development mode: Simulating adapter reset")
                return True

            adapter_interface = dbus.Interface(self.adapter, self.adapter_interface)
            
            # Power cycle the adapter
            self.adapter_props.Set(self.adapter_interface, 'Powered', False)
            time.sleep(1)
            self.adapter_props.Set(self.adapter_interface, 'Powered', True)
            
            logger.info("Bluetooth adapter reset successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to reset adapter: {str(e)}")
            return False

    def get_bluetooth_status(self):
        """Get current Bluetooth adapter status."""
        try:
            if self.is_development:
                return {
                    "status": "active",
                    "powered": True,
                    "discovering": True,
                    "discoverable": True,
                    "address": "00:00:00:00:00:00",
                    "name": "Mock Bluetooth Adapter"
                }

            status = {
                "status": "inactive",
                "powered": False,
                "discovering": False,
                "discoverable": False,
                "address": "",
                "name": ""
            }

            if self.adapter and self.adapter_props:
                status["powered"] = bool(self.adapter_props.Get(self.adapter_interface, 'Powered'))
                status["discovering"] = bool(self.adapter_props.Get(self.adapter_interface, 'Discovering'))
                status["discoverable"] = bool(self.adapter_props.Get(self.adapter_interface, 'Discoverable'))
                status["address"] = str(self.adapter_props.Get(self.adapter_interface, 'Address'))
                status["name"] = str(self.adapter_props.Get(self.adapter_interface, 'Name'))
                status["status"] = "active" if status["powered"] else "inactive"

            return status
        except Exception as e:
            logger.error(f"Error getting Bluetooth status: {str(e)}")
            return {"status": "error", "error": str(e)}

    def update_status_characteristic(self):
        """Update status characteristic with current Bluetooth status."""
        try:
            status = self.get_bluetooth_status()
            status_json = json.dumps(status)
            if hasattr(self, 'status_characteristic'):
                self.status_characteristic.Set(
                    'org.bluez.GattCharacteristic1',
                    'Value',
                    dbus.Array([dbus.Byte(ord(c)) for c in status_json])
                )
        except Exception as e:
            logger.error(f"Error updating status characteristic: {str(e)}")

    def start_status_updates(self):
        """Start periodic status updates in a separate thread."""
        def update_loop():
            while self.running:
                self.update_status_characteristic()
                time.sleep(5)  # Update every 5 seconds

        self.status_update_thread = threading.Thread(target=update_loop)
        self.status_update_thread.daemon = True
        self.status_update_thread.start()

    def cleanup(self):
        """Cleanup Bluetooth adapter and stop status updates."""
        try:
            if self.is_development:
                logger.info("Development mode: Skipping cleanup")
                return

            self.running = False
            if self.status_update_thread:
                self.status_update_thread.join()

            if self.adapter and self.adapter_props:
                self.adapter_props.Set(self.adapter_interface, 'Powered', False)
                logger.info("Cleanup completed successfully")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

    def run(self):
        """Start the GATT server."""
        try:
            if not check_bluetooth_status():
                raise Exception("Bluetooth is not available")

            if not self.setup_dbus():
                raise Exception("Failed to setup D-Bus")

            if not self.reset_adapter():
                raise Exception("Failed to reset adapter during setup")

            logger.info("D-Bus setup completed successfully")

            # Power on the adapter
            if not self.is_development:
                self.adapter_props.Set(self.adapter_interface, 'Powered', True)
            logger.info("Bluetooth adapter powered on")

            self.running = True
            self.start_status_updates()

            # Start the main event loop
            self.mainloop = GLib.MainLoop()
            self.mainloop.run()

        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            self.cleanup()
            raise

if __name__ == "__main__":
    server = BLEGATTServer()
    try:
        server.run()
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
        server.cleanup()
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        server.cleanup()
