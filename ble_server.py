import dbus.mainloop.glib
from gi.repository import GLib
import dbus.service
import time
import os
import subprocess
from logger_config import logger

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

    def _setup_dbus(self):
        """Initialize D-Bus and BlueZ interfaces with improved service registration."""
        try:
            # Initialize D-Bus mainloop first
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            self.bus = dbus.SystemBus()
            self.mainloop = GLib.MainLoop()

            # Get adapter object and verify it exists
            adapter_path = '/org/bluez/hci0'
            adapter_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, adapter_path)
            if not adapter_obj:
                raise Exception(f"No Bluetooth adapter found at {adapter_path}")

            # Initialize adapter interfaces
            self.adapter = dbus.Interface(adapter_obj, 'org.bluez.Adapter1')
            self.adapter_props = dbus.Interface(adapter_obj, DBUS_PROP_IFACE)

            # Configure adapter properties
            self._configure_adapter()

            # Initialize manager interfaces
            self.gatt_manager = dbus.Interface(adapter_obj, GATT_MANAGER_IFACE)
            self.ad_manager = dbus.Interface(adapter_obj, LE_ADVERTISING_MANAGER_IFACE)

            # Request service name with retry
            retry_count = 0
            while retry_count < 3:
                try:
                    self.dbus_service_name = dbus.service.BusName(
                        DBUS_SERVICE_NAME,
                        self.bus,
                        do_not_queue=True,
                        replace_existing=True
                    )
                    break
                except dbus.exceptions.NameExistsException:
                    retry_count += 1
                    logger.warning(f"Service name exists, retrying... ({retry_count}/3)")
                    self._cleanup_existing_service()
                    time.sleep(2)

            if not self.dbus_service_name:
                raise Exception("Failed to acquire D-Bus service name")

            return True

        except Exception as e:
            logger.error(f"D-Bus setup failed: {str(e)}", exc_info=True)
            return False

    def _configure_adapter(self):
        """Configure the Bluetooth adapter with appropriate settings."""
        try:
            properties = {
                'Powered': dbus.Boolean(True),
                'Discoverable': dbus.Boolean(True),
                'DiscoverableTimeout': dbus.UInt32(0),  # No timeout
                'Pairable': dbus.Boolean(True),
                'PairableTimeout': dbus.UInt32(0),  # No timeout
                'Alias': dbus.String('PiGattServer')
            }

            for prop, value in properties.items():
                self.adapter_props.Set('org.bluez.Adapter1', prop, value)
                logger.info(f"Set adapter property {prop} to {value}")

            # Short delay to allow properties to take effect
            time.sleep(1)

        except Exception as e:
            logger.error(f"Failed to configure adapter: {str(e)}")
            raise

    def register_advertisement(self):
        """Register advertisement with improved configuration."""
        try:
            if self.is_development:
                logger.info("Development mode: Simulating advertisement registration")
                return True

            self.advertisement = Advertisement(self.bus, 0, 'peripheral')

            # Configure advertisement properties
            self.advertisement.service_uuids = [ServiceDefinitions.CUSTOM_SERVICE_UUID]
            self.advertisement.local_name = "PiGattServer"
            self.advertisement.include_tx_power = True

            # Register advertisement with retry
            retry_count = 0
            max_retries = 3

            while retry_count < max_retries:
                try:
                    self.ad_manager.RegisterAdvertisement(
                        self.advertisement.get_path(),
                        {},
                        timeout=30
                    )
                    logger.info("Advertisement registered successfully")
                    return True
                except dbus.exceptions.DBusException as e:
                    retry_count += 1
                    if retry_count >= max_retries:
                        logger.error(f"Failed to register advertisement after {max_retries} attempts")
                        raise
                    logger.warning(f"Advertisement registration failed, retrying ({retry_count}/{max_retries})")
                    time.sleep(2)

            return False

        except Exception as e:
            logger.error(f"Failed to register advertisement: {str(e)}")
            self._cleanup_advertisement()
            return False

    def register_service(self):
        """Register GATT service with improved reliability."""
        try:
            if self.is_development:
                logger.info("Development mode: Simulating service registration")
                return True

            # Create and register the service
            self.service = GattService(self.bus, 0, ServiceDefinitions.CUSTOM_SERVICE_UUID)

            # Register characteristics
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
                logger.info(f"Added characteristic: {name} at {char.path}")

            # Register application with retry
            app_path = dbus.ObjectPath(DBUS_BASE_PATH)
            retry_count = 0
            max_retries = 3

            while retry_count < max_retries:
                try:
                    self.gatt_manager.RegisterApplication(
                        app_path,
                        {},
                        timeout=30
                    )
                    logger.info("Service registered successfully")
                    return True
                except dbus.exceptions.DBusException as e:
                    retry_count += 1
                    if retry_count >= max_retries:
                        logger.error(f"Failed to register service after {max_retries} attempts")
                        raise
                    logger.warning(f"Service registration failed, retrying ({retry_count}/{max_retries})")
                    time.sleep(2)

            return False

        except Exception as e:
            logger.error(f"Error during service registration: {str(e)}")
            return False

    def run(self):
        """Start the GATT server with improved initialization sequence."""
        try:
            # Ensure clean state
            self._cleanup_existing_service()
            time.sleep(1)

            # Setup D-Bus
            if not self._setup_dbus():
                raise Exception("Failed to setup D-Bus")

            # Register service first
            if not self.register_service():
                raise Exception("Failed to register service")

            # Then register advertisement
            if not self.register_advertisement():
                raise Exception("Failed to register advertisement")

            logger.info("GATT server started successfully")
            self.mainloop.run()

        except Exception as e:
            logger.error(f"Error starting GATT server: {str(e)}")
            self.cleanup()