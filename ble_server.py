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
import subprocess

# Import mock D-Bus for development mode
if "REPL_ID" in os.environ:
    from mock_dbus import MockMessageBus
    logger.info("Using Mock D-Bus implementation for development")
else:
    logger.info("Using dbus-python implementation")

from service_definitions import ServiceDefinitions, CharacteristicProperties

class BluetoothError(Exception):
    """Custom exception for Bluetooth-related errors."""
    pass

def retry_with_backoff(max_retries=5, base_delay=1):
    """Decorator for retry mechanism with exponential backoff.
    
    Args:
        max_retries (int): Maximum number of retry attempts
        base_delay (float): Initial delay between retries in seconds
    """
    def decorator(func):
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except dbus.exceptions.DBusException as e:
                    last_exception = e
                    if "org.bluez.Error.Busy" in str(e):
                        delay = base_delay * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"Adapter busy, retrying in {delay:.1f} seconds (attempt {attempt + 1}/{max_retries})")
                        time.sleep(delay)
                    else:
                        raise
                except Exception as e:
                    logger.error(f"Unexpected error in {func.__name__}: {str(e)}")
                    raise
            
            if last_exception:
                logger.error(f"Max retries ({max_retries}) exceeded in {func.__name__}")
                raise last_exception
            
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except dbus.exceptions.DBusException as e:
                    last_exception = e
                    if "org.bluez.Error.Busy" in str(e):
                        delay = base_delay * (2 ** attempt)  # Exponential backoff
                        logger.warning(f"Adapter busy, retrying in {delay:.1f} seconds (attempt {attempt + 1}/{max_retries})")
                        await asyncio.sleep(delay)
                    else:
                        raise
                except Exception as e:
                    logger.error(f"Unexpected error in {func.__name__}: {str(e)}")
                    raise
            
            if last_exception:
                logger.error(f"Max retries ({max_retries}) exceeded in {func.__name__}")
                raise last_exception
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator

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

    def force_reset_bluetooth(self):
        """Force reset Bluetooth by stopping and starting the service."""
        try:
            if self.is_development:
                logger.info("Development mode: Simulating force reset")
                return True

            # Stop any existing bluetoothd processes
            subprocess.run(['pkill', 'bluetoothd'], check=False)
            time.sleep(2)

            # Restart bluetooth service
            subprocess.run(['systemctl', 'restart', 'bluetooth'], check=True)
            time.sleep(3)
            
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to force reset Bluetooth: {str(e)}")
            return False

    @retry_with_backoff(max_retries=5, base_delay=1)
    def reset_adapter(self, force=False):
        """Reset Bluetooth adapter with optional force reset."""
        try:
            if self.is_development:
                logger.info("Development mode: Simulating adapter reset")
                return True

            if force:
                logger.info("Performing force reset of Bluetooth adapter")
                if not self.force_reset_bluetooth():
                    raise BluetoothError("Force reset failed")

            adapter_interface = dbus.Interface(self.adapter, self.adapter_interface)
            
            # Power cycle the adapter
            self.adapter_props.Set(self.adapter_interface, 'Powered', False)
            time.sleep(2)
            self.adapter_props.Set(self.adapter_interface, 'Powered', True)
            time.sleep(1)
            
            logger.info("Bluetooth adapter reset successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to reset adapter: {str(e)}")
            if not force and "org.bluez.Error.Busy" in str(e):
                logger.info("Attempting force reset due to busy adapter")
                return self.reset_adapter(force=True)
            raise

    @retry_with_backoff(max_retries=5, base_delay=1)
    def set_discoverable(self, enable=True, timeout=180):
        """Enable or disable adapter discoverability with timeout."""
        try:
            if self.is_development:
                logger.info(f"Development mode: {'Enabling' if enable else 'Disabling'} discoverability")
                return True

            if not self.adapter_props:
                raise BluetoothError("Adapter not initialized")

            current_state = bool(self.adapter_props.Get(self.adapter_interface, 'Discoverable'))
            if current_state == enable:
                logger.info(f"Adapter already {'discoverable' if enable else 'non-discoverable'}")
                return True

            self.adapter_props.Set(self.adapter_interface, 'Discoverable', enable)
            if enable:
                self.adapter_props.Set(self.adapter_interface, 'DiscoverableTimeout', dbus.UInt32(timeout))
            
            logger.info(f"Successfully {'enabled' if enable else 'disabled'} discoverability")
            return True
        except Exception as e:
            logger.error(f"Failed to set discoverable mode: {str(e)}")
            raise

    def get_bluetooth_status(self):
        """Get current Bluetooth adapter status."""
        try:
            if self.is_development:
                return {
                    "status": "active",
                    "powered": True,
                    "discovering": True,
                    "discoverable": True,
                    "discoverable_timeout": 180,
                    "address": "00:00:00:00:00:00",
                    "name": "Mock Bluetooth Adapter"
                }

            status = {
                "status": "inactive",
                "powered": False,
                "discovering": False,
                "discoverable": False,
                "discoverable_timeout": 0,
                "address": "",
                "name": ""
            }

            if self.adapter and self.adapter_props:
                status["powered"] = bool(self.adapter_props.Get(self.adapter_interface, 'Powered'))
                status["discovering"] = bool(self.adapter_props.Get(self.adapter_interface, 'Discovering'))
                status["discoverable"] = bool(self.adapter_props.Get(self.adapter_interface, 'Discoverable'))
                status["discoverable_timeout"] = int(self.adapter_props.Get(self.adapter_interface, 'DiscoverableTimeout'))
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
                self.set_discoverable(False)
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

            # Power on the adapter and set initial discoverable state
            if not self.is_development:
                self.adapter_props.Set(self.adapter_interface, 'Powered', True)
                self.set_discoverable(True, 180)  # Enable discoverability for 3 minutes
            logger.info("Bluetooth adapter powered on and configured")

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
