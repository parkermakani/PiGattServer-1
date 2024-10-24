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

BLUEZ_SERVICE_NAME = 'org.bluez'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHRC_IFACE = 'org.bluez.GattCharacteristic1'
LE_ADVERTISEMENT_IFACE = 'org.bluez.LEAdvertisement1'

class GattService(dbus.service.Object):
    """
    GATT Service implementation using D-Bus.
    """
    
    def __init__(self, bus, index, uuid):
        self.path = f'/org/bluez/example/service{index}'
        self.uuid = uuid
        self.bus = bus
        self.characteristics = []
        self.next_index = 0
        
        if "REPL_ID" in os.environ:
            logger.info(f"Development mode: Simulating GATT service at {self.path}")
            return
            
        super().__init__(bus, self.path)

    def get_properties(self):
        """Return the service properties dictionary."""
        return {
            GATT_SERVICE_IFACE: {
                'UUID': dbus.String(self.uuid),
                'Primary': dbus.Boolean(True),
                'Characteristics': dbus.Array(
                    self.get_characteristic_paths(),
                    signature='o'
                )
            }
        }

    def get_path(self):
        """Return the D-Bus path of the service."""
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, characteristic):
        """Add a characteristic to this service."""
        self.characteristics.append(characteristic)

    def get_characteristic_paths(self):
        """Get the D-Bus paths of all characteristics."""
        result = []
        for chrc in self.characteristics:
            result.append(chrc.get_path())
        return result

    @dbus.service.method(DBUS_PROP_IFACE,
                        in_signature='s',
                        out_signature='a{sv}')
    def GetAll(self, interface):
        """Get all properties for the specified interface."""
        if interface != GATT_SERVICE_IFACE:
            raise dbus.exceptions.DBusException(
                'org.bluez.Error.InvalidArguments',
                f'Unknown interface: {interface}')

        return self.get_properties()[GATT_SERVICE_IFACE]

class GattCharacteristic(dbus.service.Object):
    """
    GATT Characteristic implementation using D-Bus.
    """
    
    def __init__(self, bus, index, uuid, properties, service):
        self.path = f'{service.path}/char{index}'
        self.uuid = uuid
        self.service = service
        self.flags = properties
        self.notifying = False
        self.value = dbus.Array([dbus.Byte(0)], signature=dbus.Signature('y'))
        self.bus = bus
        
        if "REPL_ID" in os.environ:
            logger.info(f"Development mode: Simulating GATT characteristic at {self.path}")
            return
            
        super().__init__(bus, self.path)

    def get_properties(self):
        """Return the characteristic properties dictionary."""
        return {
            GATT_CHRC_IFACE: {
                'Service': self.service.get_path(),
                'UUID': dbus.String(self.uuid),
                'Flags': dbus.Array(self.flags, signature='s'),
                'Notifying': dbus.Boolean(self.notifying)
            }
        }

    def get_path(self):
        """Return the D-Bus path of the characteristic."""
        return dbus.ObjectPath(self.path)

    @dbus.service.method(GATT_CHRC_IFACE,
                        in_signature='a{sv}', 
                        out_signature='ay')
    def ReadValue(self, options):
        """Read the characteristic value."""
        logger.info(f'Reading characteristic value at {self.path}')
        return self.value

    @dbus.service.method(GATT_CHRC_IFACE,
                        in_signature='aya{sv}', 
                        out_signature='')
    def WriteValue(self, value, options):
        """Write the characteristic value."""
        logger.info(f'Writing characteristic value at {self.path}')
        self.value = dbus.Array([dbus.Byte(b) for b in value], signature='y')
        
    @dbus.service.method(GATT_CHRC_IFACE,
                        in_signature='', 
                        out_signature='')
    def StartNotify(self):
        """Start notifications for this characteristic."""
        if self.notifying:
            return
        self.notifying = True
        logger.info(f'Started notifications for {self.path}')

    @dbus.service.method(GATT_CHRC_IFACE,
                        in_signature='', 
                        out_signature='')
    def StopNotify(self):
        """Stop notifications for this characteristic."""
        if not self.notifying:
            return
        self.notifying = False
        logger.info(f'Stopped notifications for {self.path}')

    @dbus.service.method(DBUS_PROP_IFACE,
                        in_signature='s',
                        out_signature='a{sv}')
    def GetAll(self, interface):
        """Get all properties for the specified interface."""
        if interface != GATT_CHRC_IFACE:
            raise dbus.exceptions.DBusException(
                'org.bluez.Error.InvalidArguments',
                f'Unknown interface: {interface}')

        return self.get_properties()[GATT_CHRC_IFACE]

class Advertisement(dbus.service.Object):
    """
    LEAdvertisement implementation using D-Bus.
    """
    def __init__(self, bus, index, advertising_type):
        self.path = f'/org/bluez/example/advertisement{index}'
        self.bus = bus
        self.ad_type = advertising_type
        self.service_uuids = [ServiceDefinitions.CUSTOM_SERVICE_UUID]
        self.manufacturer_data = {}
        self.solicit_uuids = []
        self.service_data = {}
        self.local_name = 'BLE GATT Server'
        self.include_tx_power = True
        
        if "REPL_ID" in os.environ:
            logger.info(f"Development mode: Simulating advertisement at {self.path}")
            return
            
        super().__init__(bus, self.path)

    def get_properties(self):
        """Return the advertisement properties dictionary."""
        properties = {
            LE_ADVERTISEMENT_IFACE: {
                'Type': self.ad_type,
                'ServiceUUIDs': dbus.Array(self.service_uuids, signature='s'),
                'LocalName': dbus.String(self.local_name),
                'IncludeTxPower': dbus.Boolean(self.include_tx_power)
            }
        }
        return properties

    @dbus.service.method(LE_ADVERTISEMENT_IFACE,
                        in_signature='',
                        out_signature='')
    def Release(self):
        """Release the advertisement."""
        logger.info(f'Released advertisement at {self.path}')

    @dbus.service.method(DBUS_PROP_IFACE,
                        in_signature='s',
                        out_signature='a{sv}')
    def GetAll(self, interface):
        """Get all properties for the specified interface."""
        if interface != LE_ADVERTISEMENT_IFACE:
            raise dbus.exceptions.DBusException(
                'org.bluez.Error.InvalidArguments',
                f'Unknown interface: {interface}')

        return self.get_properties()[LE_ADVERTISEMENT_IFACE]

class BLEGATTServer:
    def __init__(self):
        self.is_development = "REPL_ID" in os.environ
        self.mainloop = None
        self.bus = None
        self.service = None
        self.advertisement = None
        self.gatt_manager = None
        self.ad_manager = None
        self.dbus_service_name = None
        self._setup_dbus()

    def _setup_dbus(self):
        """Initialize D-Bus and BlueZ interfaces."""
        try:
            if self.is_development:
                self.bus = MockMessageBus()
                return True

            # Ensure bluetoothd is running
            self.ensure_bluetoothd_running()

            # Initialize D-Bus mainloop
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            self.bus = dbus.SystemBus()
            self.mainloop = GLib.MainLoop()

            # Request D-Bus service name
            self.dbus_service_name = dbus.service.BusName(
                'org.bluez.example',
                self.bus,
                do_not_queue=True
            )

            # Initialize adapter and properties interface
            adapter_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, '/org/bluez/hci0')
            self.adapter = dbus.Interface(adapter_obj, 'org.bluez.Adapter1')
            self.adapter_props = dbus.Interface(adapter_obj, DBUS_PROP_IFACE)

            # Initialize GattManager1 and LEAdvertisingManager1 interfaces
            self.gatt_manager = dbus.Interface(
                adapter_obj,
                GATT_MANAGER_IFACE
            )
            self.ad_manager = dbus.Interface(
                adapter_obj,
                LE_ADVERTISING_MANAGER_IFACE
            )

            # Reset adapter
            self.reset_adapter()
            logger.info("D-Bus setup completed successfully")
            return True

        except dbus.exceptions.DBusException as e:
            if "Name already exists" in str(e):
                logger.error("D-Bus service name already in use. Trying to release existing service...")
                self._release_existing_service()
                return self._setup_dbus()
            logger.error(f"Failed to setup D-Bus: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Failed to setup D-Bus: {str(e)}")
            return False

    def _release_existing_service(self):
        """Attempt to release an existing D-Bus service."""
        try:
            subprocess.run(['systemctl', 'restart', 'bluetooth'], check=True)
            time.sleep(2)
        except Exception as e:
            logger.error(f"Failed to release existing service: {str(e)}")

    def ensure_bluetoothd_running(self):
        """Ensure that bluetoothd service is running and restart if necessary."""
        try:
            # Check if bluetoothd is active
            result = subprocess.run(['systemctl', 'is-active', 'bluetooth'], capture_output=True, text=True)
            if "inactive" in result.stdout or result.returncode != 0:
                logger.info("Bluetooth service is not active. Starting bluetoothd...")
                subprocess.run(['systemctl', 'start', 'bluetooth'], check=True)
            else:
                logger.info("Bluetooth service is already active.")
        except Exception as e:
            logger.error(f"Error while checking or starting bluetoothd: {str(e)}")

    def reset_adapter(self):
        """Reset Bluetooth adapter with retry mechanism."""
        if self.is_development:
            logger.info("Development mode: Simulating adapter reset")
            return True

        try:
            logger.info("Resetting Bluetooth adapter...")
            # Use Properties interface to set adapter power state
            self.adapter_props.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(0))
            time.sleep(1)
            self.adapter_props.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(1))
            logger.info("Bluetooth adapter reset successfully")
            time.sleep(1)  # Allow adapter to stabilize
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

    def register_advertisement(self):
        """Register advertisement with LEAdvertisingManager1."""
        try:
            if self.is_development:
                logger.info("Development mode: Simulating advertisement registration")
                return True

            self.advertisement = Advertisement(self.bus, 0, 'peripheral')
            try:
                self.ad_manager.RegisterAdvertisement(
                    self.advertisement.get_path(),
                    dbus.Dictionary({}, signature='sv')
                )
                logger.info("Advertisement registered successfully")
                return True
            except dbus.exceptions.DBusException as e:
                logger.error(f"Failed to register advertisement: {str(e)}")
                self._cleanup_advertisement()
                return False

        except Exception as e:
            logger.error(f"Error during advertisement registration: {str(e)}")
            return False

    def _cleanup_advertisement(self):
        """Clean up advertisement registration."""
        try:
            if self.is_development:
                logger.info("Development mode: Skipping advertisement cleanup")
                return

            if hasattr(self, 'ad_manager') and self.advertisement:
                try:
                    self.ad_manager.UnregisterAdvertisement(self.advertisement.get_path())
                except Exception as e:
                    logger.error(f"Failed to unregister advertisement: {str(e)}")

        except Exception as e:
            logger.error(f"Error during advertisement cleanup: {str(e)}")

    def register_service(self):
        """Register GATT service and characteristics with improved reliability."""
        try:
            if self.is_development:
                logger.info("Development mode: Simulating service registration")
                return True

            # Create and register the service
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

            # Register application and advertisement with retry
            max_retries = 3
            retry_count = 0
            while retry_count < max_retries:
                try:
                    app_path = dbus.ObjectPath('/org/bluez/example')
                    self.gatt_manager.RegisterApplication(
                        app_path,
                        dbus.Dictionary({}, signature='sv'),
                        timeout=20
                    )
                    logger.info("Service registered successfully")

                    if not self.register_advertisement():
                        raise Exception("Failed to register advertisement")

                    return True

                except dbus.exceptions.DBusException as e:
                    retry_count += 1
                    if retry_count >= max_retries:
                        logger.error(f"Failed to register service after {max_retries} attempts")
                        self._cleanup_service()
                        raise
                    logger.info(f"Retrying service registration ({retry_count}/{max_retries})")
                    time.sleep(2)

        except Exception as e:
            logger.error(f"Error during service registration: {str(e)}")
            return False

    def _cleanup_service(self):
        """Clean up service registration."""
        try:
            if self.is_development:
                logger.info("Development mode: Skipping service cleanup")
                return

            self._cleanup_advertisement()

            if hasattr(self, 'gatt_manager'):
                try:
                    app_path = dbus.ObjectPath('/org/bluez/example')
                    self.gatt_manager.UnregisterApplication(app_path)
                except Exception as e:
                    logger.error(f"Failed to unregister application: {str(e)}")

        except Exception as e:
            logger.error(f"Error during service cleanup: {str(e)}")

    def get_adapter_properties(self):
        """Get all adapter properties using Properties interface."""
        if self.is_development:
            return {"Powered": True, "Discoverable": True}
        try:
            return self.adapter_props.GetAll('org.bluez.Adapter1')
        except Exception as e:
            logger.error(f"Failed to get adapter properties: {str(e)}")
            return {}

    def run(self):
        """Start the GATT server and run the main loop."""
        try:
            if not check_bluetooth_status():
                raise Exception("Bluetooth is not available")

            # Add a delay before registering the service to ensure BlueZ is ready
            logger.info("Waiting for 2 seconds to allow BlueZ to stabilize...")
            time.sleep(2)

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
                if hasattr(self, 'dbus_service_name'):
                    del self.dbus_service_name
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
