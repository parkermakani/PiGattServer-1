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
                    if "org.bluez.Error.Busy" in str(e) or "org.freedesktop.DBus.Error.NoReply" in str(e):
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"D-Bus operation failed, retrying in {delay:.1f} seconds (attempt {attempt + 1}/{max_retries})")
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
                    if "org.bluez.Error.Busy" in str(e) or "org.freedesktop.DBus.Error.NoReply" in str(e):
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"D-Bus operation failed, retrying in {delay:.1f} seconds (attempt {attempt + 1}/{max_retries})")
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
                'Value': dbus.Array(self.value, signature='y'),
            }
        }

    @dbus.service.method('org.bluez.GattCharacteristic1',
                        in_signature='a{sv}', out_signature='ay')
    def ReadValue(self, options):
        return dbus.Array(self.value, signature='y')

    @dbus.service.method('org.bluez.GattCharacteristic1',
                        in_signature='aya{sv}')
    def WriteValue(self, value, options):
        self.value = value

class GattService(dbus.service.Object):
    PATH_BASE = '/org/bluez/example/service'

    def __init__(self, bus, index, uuid, primary=True):
        self.path = f'{self.PATH_BASE}{index}'
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            'org.bluez.GattService1': {
                'UUID': dbus.String(self.uuid),
                'Primary': dbus.Boolean(self.primary),
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
            result.append(dbus.ObjectPath(chrc.path))
        return result

    def get_characteristics(self):
        return self.characteristics

    @dbus.service.method(dbus.PROPERTIES_IFACE,
                        in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != 'org.bluez.GattService1':
            raise dbus.exceptions.DBusException(
                'org.bluez.Error.InvalidArgs',
                f'GetAll called with invalid interface: {interface}')
        return self.get_properties()['org.bluez.GattService1']

class Advertisement(dbus.service.Object):
    def __init__(self, bus, index, advertising_type):
        self.path = f'/org/bluez/example/advertisement{index}'
        self.bus = bus
        self.ad_type = advertising_type
        self.service_uuids = None
        self.manufacturer_data = None
        self.solicit_uuids = None
        self.service_data = None
        self.local_name = None
        self.include_tx_power = None
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        properties = dict()
        properties['Type'] = self.ad_type
        if self.service_uuids is not None:
            properties['ServiceUUIDs'] = dbus.Array(self.service_uuids, signature='s')
        if self.manufacturer_data is not None:
            properties['ManufacturerData'] = dbus.Dictionary(
                self.manufacturer_data, signature='qv')
        if self.solicit_uuids is not None:
            properties['SolicitUUIDs'] = dbus.Array(self.solicit_uuids, signature='s')
        if self.service_data is not None:
            properties['ServiceData'] = dbus.Dictionary(self.service_data, signature='sv')
        if self.local_name is not None:
            properties['LocalName'] = dbus.String(self.local_name)
        if self.include_tx_power is not None:
            properties['IncludeTxPower'] = dbus.Boolean(self.include_tx_power)
        return {dbus.PROPERTIES_IFACE: properties}

    @dbus.service.method(dbus.PROPERTIES_IFACE,
                        in_signature='s',
                        out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != 'org.bluez.LEAdvertisement1':
            raise dbus.exceptions.DBusException(
                'org.bluez.Error.InvalidArgs',
                f'GetAll called with invalid interface: {interface}')
        return self.get_properties()[dbus.PROPERTIES_IFACE]

    @dbus.service.method('org.bluez.LEAdvertisement1',
                        in_signature='',
                        out_signature='')
    def Release(self):
        logger.info(f'Released advertisement: {self.path}')

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
        self.bus = None
        self.setup_timeout = 30  # seconds
        self.registration_timeout = 15  # seconds

    @retry_with_backoff(max_retries=3, base_delay=2)
    def reset_adapter(self, force=False):
        """Reset the Bluetooth adapter with retry mechanism."""
        try:
            if self.is_development:
                logger.info("Development mode: Simulating adapter reset")
                return True

            # Try normal reset first
            try:
                self.adapter_props.Set(self.adapter_interface, 'Powered', False)
                time.sleep(1)
                self.adapter_props.Set(self.adapter_interface, 'Powered', True)
                return True
            except dbus.exceptions.DBusException as e:
                if "org.bluez.Error.Busy" in str(e):
                    if not force:
                        logger.info("Attempting force reset due to busy adapter")
                        return self.reset_adapter(force=True)
                    else:
                        logger.info("Performing force reset of Bluetooth adapter")
                        # Force reset using system commands
                        try:
                            subprocess.run(['systemctl', 'stop', 'bluetooth-mesh.service'], check=False)
                            subprocess.run(['systemctl', 'stop', 'bluealsa.service'], check=False)
                            subprocess.run(['systemctl', 'stop', 'bluetooth.service'], check=True)
                            time.sleep(2)
                            subprocess.run(['systemctl', 'start', 'bluetooth.service'], check=True)
                            time.sleep(5)
                            subprocess.run(['systemctl', 'restart', 'bluetooth-mesh.service'], check=False)
                            subprocess.run(['systemctl', 'restart', 'bluealsa.service'], check=False)
                            
                            # Re-initialize D-Bus connection
                            self.adapter = self.bus.get_object('org.bluez', '/org/bluez/hci0')
                            self.adapter_props = dbus.Interface(self.adapter, 'org.freedesktop.DBus.Properties')
                            self.adapter_props.Set(self.adapter_interface, 'Powered', True)
                            
                            logger.info("Bluetooth adapter reset successfully")
                            return True
                        except subprocess.CalledProcessError as e:
                            logger.error(f"Failed to force reset adapter: {str(e)}")
                            return False
                else:
                    raise

        except Exception as e:
            logger.error(f"Failed to reset adapter: {str(e)}")
            return False

    @retry_with_backoff(max_retries=3, base_delay=2)
    def start_advertising(self):
        """Start advertising the GATT service."""
        try:
            if self.is_development:
                logger.info("Development mode: Simulating advertisement start")
                return True

            # Create and configure advertisement
            self.advertisement = Advertisement(self.bus, 0, 'peripheral')
            self.advertisement.service_uuids = [ServiceDefinitions.CUSTOM_SERVICE_UUID]
            self.advertisement.include_tx_power = True

            # Get LEAdvertisingManager1 interface
            ad_manager = dbus.Interface(
                self.bus.get_object('org.bluez', '/org/bluez/hci0'),
                'org.bluez.LEAdvertisingManager1'
            )

            # Register advertisement
            ad_manager.RegisterAdvertisement(
                self.advertisement.get_path(),
                {}
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
                logger.info("Development mode: Simulating advertisement stop")
                return True

            if self.advertisement:
                ad_manager = dbus.Interface(
                    self.bus.get_object('org.bluez', '/org/bluez/hci0'),
                    'org.bluez.LEAdvertisingManager1'
                )
                ad_manager.UnregisterAdvertisement(self.advertisement.get_path())
                self.advertisement = None
                logger.info("Stopped advertising")
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
                gatt_manager = dbus.Interface(
                    self.bus.get_object('org.bluez', '/org/bluez/hci0'),
                    'org.bluez.GattManager1'
                )
                gatt_manager.UnregisterApplication(self.service.get_path())
                self.service = None
                logger.info("Service unregistered successfully")
            return True

        except dbus.exceptions.DBusException as e:
            if "org.bluez.Error.DoesNotExist" in str(e):
                logger.error(f"Failed to unregister service: {str(e)}")
            else:
                raise
        except Exception as e:
            logger.error(f"Error unregistering service: {str(e)}")
            return False

    def setup_dbus(self):
        """Initialize D-Bus connection and get Bluetooth adapter."""
        try:
            if self.is_development:
                return True

            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            self.bus = dbus.SystemBus()

            # Add timeout for adapter object retrieval
            start_time = time.time()
            while time.time() - start_time < self.setup_timeout:
                try:
                    self.adapter = self.bus.get_object('org.bluez', '/org/bluez/hci0')
                    self.adapter_props = dbus.Interface(self.adapter, 'org.freedesktop.DBus.Properties')
                    return True
                except dbus.exceptions.DBusException as e:
                    if time.time() - start_time < self.setup_timeout:
                        logger.warning(f"D-Bus setup retry: {str(e)}")
                        time.sleep(1)
                    else:
                        raise

            raise BluetoothError("D-Bus setup timeout exceeded")
            
        except Exception as e:
            logger.error(f"Failed to setup D-Bus: {str(e)}")
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

            # Get GattManager1 interface with timeout
            start_time = time.time()
            gatt_manager = None
            while time.time() - start_time < self.registration_timeout:
                try:
                    gatt_manager = dbus.Interface(
                        self.bus.get_object('org.bluez', '/org/bluez/hci0'),
                        'org.bluez.GattManager1'
                    )
                    break
                except dbus.exceptions.DBusException as e:
                    if time.time() - start_time < self.registration_timeout:
                        logger.warning(f"GattManager1 interface retry: {str(e)}")
                        time.sleep(1)
                    else:
                        raise BluetoothError("Failed to get GattManager1 interface")

            if not gatt_manager:
                raise BluetoothError("Failed to obtain GattManager1 interface")

            # Register application with timeout
            start_time = time.time()
            while time.time() - start_time < self.registration_timeout:
                try:
                    gatt_manager.RegisterApplication(
                        dbus.ObjectPath(self.service.path),
                        {}
                    )
                    break
                except dbus.exceptions.DBusException as e:
                    if time.time() - start_time < self.registration_timeout:
                        logger.warning(f"Service registration retry: {str(e)}")
                        time.sleep(1)
                    else:
                        raise

            logger.info("Service and characteristics registered successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to register service: {str(e)}")
            # Cleanup on registration failure
            self.unregister_service()
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

                # Add retry mechanism for service registration
                retry_count = 0
                max_retries = 3
                while retry_count < max_retries:
                    if self.register_service():
                        break
                    retry_count += 1
                    if retry_count < max_retries:
                        logger.info(f"Retrying service registration ({retry_count}/{max_retries})")
                        time.sleep(2)
                
                if retry_count >= max_retries:
                    raise BluetoothError("Failed to register service after multiple attempts")

                if not self.start_advertising():
                    self.unregister_service()
                    raise BluetoothError("Failed to start advertising")
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

            # Add timeout for cleanup operations
            cleanup_timeout = 10
            start_time = time.time()

            while time.time() - start_time < cleanup_timeout:
                try:
                    self.stop_advertising()
                    self.unregister_service()
                    break
                except Exception as e:
                    if time.time() - start_time < cleanup_timeout:
                        logger.warning(f"Cleanup retry: {str(e)}")
                        time.sleep(1)
                    else:
                        logger.error(f"Cleanup timeout exceeded: {str(e)}")

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
