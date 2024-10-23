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

def retry_on_failure(max_retries=3, delay=1):
    """Decorator for retrying operations with exponential backoff."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    wait_time = delay * (2 ** attempt)
                    logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {str(e)}")
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
            raise last_exception
        return wrapper
    return decorator

class GattCharacteristic(dbus.service.Object if not "REPL_ID" in os.environ else object):
    """GATT characteristic implementation with proper D-Bus method signatures."""
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
    """GATT service implementation with proper D-Bus interface."""
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
        self._shutdown_event = threading.Event()
        self._shutdown_timeout = 10  # seconds
        self._status_update_interval = 1  # Update status every second

    def get_bluetooth_status(self):
        """Get current Bluetooth adapter status."""
        try:
            if self.is_development:
                return {
                    "status": "active",
                    "powered": True,
                    "discovering": True,
                    "address": "00:00:00:00:00:00",
                    "name": "Mock Bluetooth Adapter"
                }

            status = {
                "status": "inactive",
                "powered": False,
                "discovering": False,
                "address": "",
                "name": ""
            }

            if self.adapter and self.adapter_props:
                status["powered"] = bool(self.adapter_props.Get(self.adapter_interface, 'Powered'))
                status["discovering"] = bool(self.adapter_props.Get(self.adapter_interface, 'Discovering'))
                status["address"] = str(self.adapter_props.Get(self.adapter_interface, 'Address'))
                status["name"] = str(self.adapter_props.Get(self.adapter_interface, 'Name'))
                status["status"] = "active" if status["powered"] else "inactive"

            return status
        except Exception as e:
            logger.error(f"Error getting Bluetooth status: {str(e)}")
            return {"status": "error", "error": str(e)}

    def update_status_characteristic(self):
        """Update the status characteristic with current Bluetooth status."""
        try:
            status = self.get_bluetooth_status()
            status_json = json.dumps(status).encode('utf-8')
            self.update_characteristic('status', status_json)
            return True
        except Exception as e:
            logger.error(f"Error updating status characteristic: {str(e)}")
            return False

    def start_status_updates(self):
        """Start periodic status updates."""
        def update_loop():
            while not self._shutdown_event.is_set():
                self.update_status_characteristic()
                time.sleep(self._status_update_interval)

        status_thread = threading.Thread(target=update_loop)
        status_thread.daemon = True
        status_thread.start()

    @retry_on_failure(max_retries=3, delay=1)
    def reset_adapter(self):
        """Reset the Bluetooth adapter with retry mechanism."""
        try:
            if self.is_development:
                logger.info("Development mode: Simulating adapter reset")
                return True

            if not self.adapter or not self.adapter_props:
                logger.error("Adapter not initialized")
                return False

            # Try to release the adapter if it's busy
            try:
                self.adapter.RemoveDevice('/')  # Try to remove all devices
            except:
                pass  # Ignore errors during device removal

            # Power cycle the adapter
            logger.info("Resetting Bluetooth adapter...")
            self.adapter_props.Set(self.adapter_interface, 'Powered', dbus.Boolean(False))
            time.sleep(1)  # Wait for adapter to power down

            # Check if adapter is truly powered off
            powered = self.adapter_props.Get(self.adapter_interface, 'Powered')
            if powered:
                raise Exception("Failed to power down adapter")

            self.adapter_props.Set(self.adapter_interface, 'Powered', dbus.Boolean(True))
            time.sleep(1)  # Wait for adapter to power up

            # Verify adapter is powered on
            powered = self.adapter_props.Get(self.adapter_interface, 'Powered')
            if not powered:
                raise Exception("Failed to power up adapter")

            # Reset discoverable and pairable states
            self.adapter_props.Set(self.adapter_interface, 'Discoverable', dbus.Boolean(False))
            self.adapter_props.Set(self.adapter_interface, 'Pairable', dbus.Boolean(False))

            logger.info("Bluetooth adapter reset successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to reset adapter: {str(e)}")
            raise

    def graceful_shutdown(self):
        """Initiate graceful shutdown with timeout."""
        logger.info("Initiating graceful shutdown...")
        self._shutdown_event.set()
        
        if self.mainloop:
            def shutdown_timeout():
                if self.mainloop:
                    logger.warning("Shutdown timeout reached, forcing exit...")
                    self.mainloop.quit()
            
            # Start timeout thread
            timeout_thread = threading.Timer(self._shutdown_timeout, shutdown_timeout)
            timeout_thread.start()
            
            try:
                # Perform cleanup while mainloop is still running
                self.cleanup()
            finally:
                timeout_thread.cancel()
                self.mainloop.quit()

    def cleanup(self):
        """Perform cleanup operations with enhanced error handling."""
        try:
            if not self.is_development and self._cleanup_required:
                logger.info("Performing adapter cleanup...")
                
                if self.adapter and self.adapter_props:
                    cleanup_steps = [
                        ('Disable advertising', lambda: self.adapter_props.Set(
                            self.adapter_interface, 'Discoverable', dbus.Boolean(False))),
                        ('Disable pairing', lambda: self.adapter_props.Set(
                            self.adapter_interface, 'Pairable', dbus.Boolean(False))),
                        ('Power down adapter', lambda: self.adapter_props.Set(
                            self.adapter_interface, 'Powered', dbus.Boolean(False)))
                    ]

                    for step_name, step_func in cleanup_steps:
                        try:
                            step_func()
                            logger.info(f"{step_name} completed successfully")
                        except Exception as e:
                            logger.warning(f"Error during {step_name.lower()}: {str(e)}")
                            # Continue with next step even if current step fails

                # Clear characteristics
                self.characteristics.clear()
                
                logger.info("Cleanup completed successfully")
            else:
                logger.info("Development mode: Skipping cleanup")

        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
        finally:
            self._cleanup_required = False

    @retry_on_failure(max_retries=3, delay=1)
    def setup_dbus(self):
        """Setup D-Bus connection with retry mechanism."""
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
                
                # Reset adapter on startup with retry
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

    @retry_on_failure(max_retries=3, delay=1)
    def start_advertising(self):
        """Start BLE advertising with retry mechanism."""
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
            
            # Start status updates
            self.start_status_updates()
            logger.info("Started Bluetooth status monitoring")
            
            logger.info("Started advertising GATT service")

            # Start the main loop with shutdown handling
            self.mainloop = GLib.MainLoop()
            
            def check_shutdown():
                if self._shutdown_event.is_set():
                    self.mainloop.quit()
                    return False
                return True
            
            # Add periodic shutdown check
            GLib.timeout_add(1000, check_shutdown)
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
        server.graceful_shutdown()
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        if server:
            server.graceful_shutdown()

if __name__ == "__main__":
    main()
