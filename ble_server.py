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
    """Decorator for retry mechanism with exponential backoff."""
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
                        delay = base_delay * (2 ** attempt)
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
                        delay = base_delay * (2 ** attempt)
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

    def check_service_status(self, service_name):
        """Check if a systemd service is active."""
        try:
            result = subprocess.run(['systemctl', 'is-active', service_name],
                                 capture_output=True, text=True, timeout=10)
            return result.stdout.strip() == "active"
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout while checking {service_name} status")
            return False
        except Exception as e:
            logger.error(f"Error checking {service_name} status: {str(e)}")
            return False

    def wait_for_service(self, service_name, timeout=30):
        """Wait for a service to become active."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.check_service_status(service_name):
                return True
            time.sleep(1)
        return False

    def force_reset_bluetooth(self):
        """Force reset Bluetooth by stopping and starting the service with dependency handling."""
        try:
            if self.is_development:
                logger.info("Development mode: Simulating force reset")
                return True

            # Stop dependent services first
            dependent_services = ['bluetooth-mesh', 'bluealsa']
            for service in dependent_services:
                try:
                    subprocess.run(['systemctl', 'stop', service], check=False, timeout=10)
                except Exception as e:
                    logger.warning(f"Error stopping {service}: {str(e)}")

            # Stop any existing bluetoothd processes
            try:
                subprocess.run(['pkill', '-9', 'bluetoothd'], check=False, timeout=10)
            except Exception as e:
                logger.warning(f"Error killing bluetoothd processes: {str(e)}")

            time.sleep(2)

            # Reset Bluetooth interface
            try:
                subprocess.run(['hciconfig', 'hci0', 'down'], check=False, timeout=10)
                time.sleep(1)
                subprocess.run(['hciconfig', 'hci0', 'up'], check=False, timeout=10)
            except Exception as e:
                logger.warning(f"Error resetting Bluetooth interface: {str(e)}")

            # Restart bluetooth service
            try:
                subprocess.run(['systemctl', 'restart', 'bluetooth'], check=True, timeout=30)
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to restart bluetooth service: {str(e)}")
                return False
            
            # Wait for bluetooth service to be fully active
            if not self.wait_for_service('bluetooth', timeout=30):
                logger.error("Timeout waiting for bluetooth service to become active")
                return False

            # Restart dependent services
            for service in dependent_services:
                try:
                    subprocess.run(['systemctl', 'restart', service], check=False, timeout=10)
                except Exception as e:
                    logger.warning(f"Error restarting {service}: {str(e)}")

            time.sleep(3)  # Allow time for services to stabilize
            
            return True
        except Exception as e:
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
                
                # Re-initialize D-Bus connection after force reset
                if not self.setup_dbus():
                    raise BluetoothError("Failed to reinitialize D-Bus after force reset")

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

    # ... [rest of the code remains unchanged] ...

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
