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

class GattCharacteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.value = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            'org.bluez.GattCharacteristic1': {
                'Service': self.service.get_path(),
                'UUID': self.uuid,
                'Flags': self.flags,
                'Value': self.value,
            }
        }

    @dbus.service.method('org.bluez.GattCharacteristic1',
                        in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        return self.value

    @dbus.service.method('org.bluez.GattCharacteristic1',
                        in_signature='aya{sv}')
    def WriteValue(self, value, options):
        self.value = value

class GattService(dbus.service.Object):
    def __init__(self, bus, index, uuid, primary=True):
        self.path = f'/org/bluez/example/service{index}'
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            'org.bluez.GattService1': {
                'UUID': self.uuid,
                'Primary': self.primary,
                'Characteristics': dbus.Array(
                    self.get_characteristic_paths(),
                    signature='o')
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)

    def get_characteristic_paths(self):
        result = []
        for chrc in self.characteristics:
            result.append(chrc.get_path())
        return result

    def get_characteristics(self):
        return self.characteristics

class BLEGATTServer:
    def __init__(self):
        self.is_development = "REPL_ID" in os.environ
        self.mainloop = None
        self.adapter = None
        self.adapter_props = None
        self.adapter_interface = 'org.bluez.Adapter1'
        self.status_update_thread = None
        self.running = False
        self.service = None
        self.advertisement = None

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

            dependent_services = ['bluetooth-mesh', 'bluealsa']
            for service in dependent_services:
                try:
                    subprocess.run(['systemctl', 'stop', service], check=False, timeout=10)
                except Exception as e:
                    logger.warning(f"Error stopping {service}: {str(e)}")

            try:
                subprocess.run(['pkill', '-9', 'bluetoothd'], check=False, timeout=10)
            except Exception as e:
                logger.warning(f"Error killing bluetoothd processes: {str(e)}")

            time.sleep(2)

            try:
                subprocess.run(['hciconfig', 'hci0', 'down'], check=False, timeout=10)
                time.sleep(1)
                subprocess.run(['hciconfig', 'hci0', 'up'], check=False, timeout=10)
            except Exception as e:
                logger.warning(f"Error resetting Bluetooth interface: {str(e)}")

            try:
                subprocess.run(['systemctl', 'restart', 'bluetooth'], check=True, timeout=30)
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to restart bluetooth service: {str(e)}")
                return False
            
            if not self.wait_for_service('bluetooth', timeout=30):
                logger.error("Timeout waiting for bluetooth service to become active")
                return False

            for service in dependent_services:
                try:
                    subprocess.run(['systemctl', 'restart', service], check=False, timeout=10)
                except Exception as e:
                    logger.warning(f"Error restarting {service}: {str(e)}")

            time.sleep(3)
            
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
                
                if not self.setup_dbus():
                    raise BluetoothError("Failed to reinitialize D-Bus after force reset")

            adapter_interface = dbus.Interface(self.adapter, self.adapter_interface)
            
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

    def register_service(self):
        """Register GATT service and characteristics."""
        try:
            if self.is_development:
                logger.info("Development mode: Simulating service registration")
                return True

            self.service = GattService(self.bus, 0, ServiceDefinitions.CUSTOM_SERVICE_UUID)

            characteristics = [
                ('temperature', CharacteristicProperties.TEMPERATURE),
                ('humidity', CharacteristicProperties.HUMIDITY),
                ('status', CharacteristicProperties.STATUS)
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

            self.bus.get_object('org.bluez', '/org/bluez').RegisterService(
                self.service.get_path(),
                {'ServiceInterface': 'org.bluez.GattService1'}
            )

            logger.info("Service and characteristics registered successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to register service: {str(e)}")
            return False

    def start_advertising(self):
        """Start advertising the GATT service."""
        try:
            if self.is_development:
                logger.info("Development mode: Simulating advertising start")
                return True

            self.advertisement = self.bus.get_object('org.bluez', '/org/bluez/advertisement0')
            ad_props = {
                'org.bluez.LEAdvertisement1': {
                    'Type': 'peripheral',
                    'ServiceUUIDs': [ServiceDefinitions.CUSTOM_SERVICE_UUID],
                    'IncludeTxPower': True
                }
            }
            self.bus.get_object('org.bluez', '/org/bluez').RegisterAdvertisement(
                self.advertisement,
                ad_props
            )

            logger.info("Started advertising GATT service")
            return True

        except Exception as e:
            logger.error(f"Failed to start advertising: {str(e)}")
            return False

    def stop_advertising(self):
        """Stop advertising the GATT service."""
        try:
            if self.is_development:
                logger.info("Development mode: Simulating advertising stop")
                return True

            if self.advertisement:
                self.bus.get_object('org.bluez', '/org/bluez').UnregisterAdvertisement(
                    self.advertisement
                )
                self.advertisement = None
                logger.info("Stopped advertising GATT service")

            return True

        except Exception as e:
            logger.error(f"Failed to stop advertising: {str(e)}")
            return False

    def unregister_service(self):
        """Unregister the GATT service."""
        try:
            if self.is_development:
                logger.info("Development mode: Simulating service unregistration")
                return True

            if self.service:
                self.bus.get_object('org.bluez', '/org/bluez').UnregisterService(
                    self.service.get_path()
                )
                self.service = None
                logger.info("Unregistered GATT service")

            return True

        except Exception as e:
            logger.error(f"Failed to unregister service: {str(e)}")
            return False

    def run(self):
        """Start the BLE GATT server."""
        try:
            if not check_bluetooth_status():
                raise BluetoothError("Bluetooth is not available")

            if not self.setup_dbus():
                raise BluetoothError("Failed to setup D-Bus")

            logger.info("Resetting Bluetooth adapter...")
            if not self.reset_adapter():
                raise BluetoothError("Failed to reset adapter during setup")

            if not self.is_development:
                self.mainloop = GLib.MainLoop()
                self.running = True

                self.mainloop_thread = threading.Thread(target=self.mainloop.run)
                self.mainloop_thread.daemon = True
                self.mainloop_thread.start()

                self.adapter_props.Set(self.adapter_interface, 'Powered', True)
                logger.info("Bluetooth adapter powered on")

                self.register_service()
                self.start_advertising()
            else:
                logger.info("Development mode: Running mock server")
                self.running = True
                while self.running:
                    time.sleep(1)

        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            self.cleanup()
            raise

    def cleanup(self):
        """Clean up resources and stop the server."""
        logger.info("Performing adapter cleanup...")
        try:
            if self.is_development:
                logger.info("Development mode: Skipping cleanup")
                return

            self.running = False

            try:
                self.stop_advertising()
                self.unregister_service()
            except Exception as e:
                logger.warning(f"Error during service cleanup: {str(e)}")

            if self.adapter_props is not None:
                try:
                    self.adapter_props.Set(self.adapter_interface, 'Powered', False)
                except Exception as e:
                    logger.warning(f"Error powering down adapter: {str(e)}")

            if self.mainloop is not None and self.mainloop.is_running():
                self.mainloop.quit()
                if hasattr(self, 'mainloop_thread'):
                    self.mainloop_thread.join(timeout=5)

            logger.info("Cleanup completed successfully")
            logger.info("GATT server stopped")

        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
        finally:
            self.running = False

if __name__ == "__main__":
    server = BLEGATTServer()
    try:
        server.run()
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
        server.cleanup()
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        server.cleanup()
