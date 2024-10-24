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

# Updated D-Bus service name and base path
DBUS_SERVICE_NAME = 'org.bluez.pigattserver'
DBUS_BASE_PATH = '/org/bluez/pigattserver'

class Advertisement(dbus.service.Object):
    """
    LEAdvertisement implementation using D-Bus.
    """
    def __init__(self, bus, index, advertising_type):
        logger.debug(f"Initializing Advertisement with index {index} and type {advertising_type}")
        self.path = f'{DBUS_BASE_PATH}/advertisement{index}'
        self.bus = bus
        self.ad_type = advertising_type
        self.service_uuids = [ServiceDefinitions.CUSTOM_SERVICE_UUID]
        self.manufacturer_data = {}
        self.solicit_uuids = []
        self.service_data = {}
        self.local_name = 'PiGattServer'
        self.include_tx_power = True

        if "REPL_ID" in os.environ:
            logger.info(f"Development mode: Simulating advertisement at {self.path}")
            return

        super().__init__(bus, self.path)
        logger.debug(f"Advertisement created at path {self.path}")

    def get_properties(self):
        """Return the advertisement properties dictionary."""
        logger.debug(f"Getting properties for advertisement at {self.path}")
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
        logger.debug(f"GetAll called for interface {interface} on advertisement {self.path}")
        if interface != LE_ADVERTISEMENT_IFACE:
            logger.error(f"Unknown interface requested: {interface}")
            raise dbus.exceptions.DBusException(
                'org.bluez.Error.InvalidArguments',
                f'Unknown interface: {interface}')

        return self.get_properties()[LE_ADVERTISEMENT_IFACE]

class BLEGATTServer:
    def __init__(self):
        logger.debug("Initializing BLEGATTServer")
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
        logger.debug("Setting up D-Bus for BLEGATTServer")
        try:
            if self.is_development:
                logger.info("Using MockMessageBus for development")
                self.bus = MockMessageBus()
                return True

            self.ensure_bluetoothd_running()

            # Initialize D-Bus mainloop
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            self.bus = dbus.SystemBus()
            self.mainloop = GLib.MainLoop()

            # Request D-Bus service name
            self.dbus_service_name = dbus.service.BusName(
                DBUS_SERVICE_NAME,
                self.bus,
                do_not_queue=True
            )
            logger.info(f"Acquired D-Bus service name: {DBUS_SERVICE_NAME}")

            # Initialize adapter and properties interface
            adapter_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, '/org/bluez/hci0')
            self.adapter = dbus.Interface(adapter_obj, 'org.bluez.Adapter1')
            self.adapter_props = dbus.Interface(adapter_obj, DBUS_PROP_IFACE)

            # Initialize GattManager1 and LEAdvertisingManager1 interfaces
            self.gatt_manager = dbus.Interface(adapter_obj, GATT_MANAGER_IFACE)
            self.ad_manager = dbus.Interface(adapter_obj, LE_ADVERTISING_MANAGER_IFACE)

            # Reset adapter
            self.reset_adapter()
            logger.info("D-Bus setup completed successfully")
            return True

        except dbus.exceptions.DBusException as e:
            if "Name already exists" in str(e):
                logger.warning("D-Bus service name already in use. Releasing existing service and retrying...")
                self._release_existing_service()
                return self._setup_dbus()
            logger.error(f"Failed to setup D-Bus: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Failed to setup D-Bus: {str(e)}")
            return False

    def _release_existing_service(self):
        """Attempt to release an existing D-Bus service."""
        logger.debug("Releasing existing D-Bus service")
        try:
            subprocess.run(['systemctl', 'restart', 'bluetooth'], check=True)
            time.sleep(2)
            logger.info("Restarted bluetooth service to release existing D-Bus name")
        except Exception as e:
            logger.error(f"Failed to release existing service: {str(e)}")

    def ensure_bluetoothd_running(self):
        """Ensure that bluetoothd service is running and restart if necessary."""
        logger.debug("Ensuring bluetoothd service is running")
        try:
            result = subprocess.run(['systemctl', 'is-active', 'bluetooth'], capture_output=True, text=True)
            if "inactive" in result.stdout or result.returncode != 0:
                logger.info("Bluetooth service is not active. Starting bluetoothd...")
                subprocess.run(['systemctl', 'start', 'bluetooth'], check=True)
                logger.info("Bluetooth service started.")
            else:
                logger.info("Bluetooth service is already active.")
        except Exception as e:
            logger.error(f"Error while checking or starting bluetoothd: {str(e)}")

    def reset_adapter(self):
        """Reset Bluetooth adapter with retry mechanism."""
        logger.debug("Resetting Bluetooth adapter")
        if self.is_development:
            logger.info("Development mode: Simulating adapter reset")
            return True

        try:
            logger.info("Resetting Bluetooth adapter...")
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
        logger.debug("Performing force reset of Bluetooth adapter")
        try:
            services = ['bluetooth', 'bluetooth-mesh', 'bluealsa']
            for service in services:
                logger.debug(f"Stopping service: {service}")
                subprocess.run(['systemctl', 'stop', service], check=False)
            time.sleep(2)
            for service in services:
                logger.debug(f"Restarting service: {service}")
                subprocess.run(['systemctl', 'restart', service], check=False)
            time.sleep(5)
            return self.reset_adapter()
        except Exception as e:
            logger.error(f"Failed to force reset adapter: {str(e)}")
            return False

    def register_advertisement(self):
        """Register advertisement with LEAdvertisingManager1."""
        logger.debug("Registering advertisement")
        try:
            if self.is_development:
                logger.info("Development mode: Simulating advertisement registration")
                return True

            self.advertisement = Advertisement(self.bus, 0, 'peripheral')
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
        logger.debug("Cleaning up advertisement")
        try:
            if hasattr(self, 'ad_manager') and self.advertisement:
                logger.info(f"Unregistering advertisement at {self.advertisement.get_path()}")
                self.ad_manager.UnregisterAdvertisement(self.advertisement.get_path())
        except Exception as e:
            logger.error(f"Failed to unregister advertisement: {str(e)}")

    def register_service(self):
        """Register GATT service and characteristics with improved reliability."""
        logger.debug("Registering GATT service")
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

            # Register application with retry
            max_retries = 3
            retry_count = 0
            while retry_count < max_retries:
                try:
                    logger.debug(f"Registering application attempt {retry_count + 1}")
                    app_path = dbus.ObjectPath(DBUS_BASE_PATH)
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
                    logger.warning(f"Failed to register service: {e}. Retrying ({retry_count}/{max_retries})...")
                    time.sleep(2)
                    if retry_count >= max_retries:
                        logger.error(f"Failed to register service after {max_retries} attempts")
                        self._cleanup_service()
                        raise

        except Exception as e:
            logger.error(f"Error during service registration: {str(e)}")
            return False

    def _cleanup_service(self):
        """Clean up service registration."""
        logger.debug("Cleaning up GATT service")
        try:
            self._cleanup_advertisement()

            if hasattr(self, 'gatt_manager'):
                app_path = dbus.ObjectPath(DBUS_BASE_PATH)
                logger.info(f"Unregistering application at {app_path}")
                self.gatt_manager.UnregisterApplication(app_path)

        except Exception as e:
            logger.error(f"Failed to unregister application: {str(e)}")

    def run(self):
        """Start the GATT server and run the main loop."""
        logger.debug("Starting BLEGATTServer run method")
        try:
            if not check_bluetooth_status():
                raise Exception("Bluetooth is not available")

            logger.info("Waiting for 2 seconds to allow BlueZ to stabilize...")
            time.sleep(2)

            if not self.register_service():
                raise Exception("Failed to register service")

            logger.info("Starting GATT server main loop")
            self.mainloop.run()

        except KeyboardInterrupt:
            logger.info("Server shutdown requested by user")
        except Exception as e:
            logger.error(f"Unexpected error in run method: {str(e)}")
        finally:
            self.cleanup()

    def cleanup(self):
        """Perform cleanup operations."""
        logger.debug("Performing cleanup of BLEGATTServer")
        try:
            self._cleanup_service()
            if hasattr(self, 'dbus_service_name'):
                logger.debug("Releasing D-Bus service name")
                del self.dbus_service_name
            if self.mainloop and self.mainloop.is_running():
                logger.debug("Quitting main loop")
                self.mainloop.quit()
            logger.info("Cleanup completed successfully")
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")
        finally:
            logger.info("GATT server stopped")

if __name__ == "__main__":
    server = BLEGATTServer()
    server.run()
