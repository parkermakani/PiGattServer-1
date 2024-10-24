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

            # Ensure bluetoothd is running and properly configured
            self._configure_bluetooth()

            # Get adapter object and verify it exists
            adapter_path = '/org/bluez/hci0'
            adapter_obj = self.bus.get_object(BLUEZ_SERVICE_NAME, adapter_path)
            if not adapter_obj:
                raise Exception(f"No Bluetooth adapter found at {adapter_path}")

            # Initialize adapter interfaces
            self.adapter = dbus.Interface(adapter_obj, 'org.bluez.Adapter1')
            self.adapter_props = dbus.Interface(adapter_obj, DBUS_PROP_IFACE)
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
                        replace_existing=True  # Add this to force replacement
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

    def _configure_bluetooth(self):
        """Configure Bluetooth system services and permissions."""
        try:
            # Stop any existing bluetooth services
            subprocess.run(['systemctl', 'stop', 'bluetooth'], check=True)
            time.sleep(1)

            # Update bluetooth configuration
            with open('/etc/bluetooth/main.conf', 'a') as f:
                f.write('\n[General]\nDisablePlugins=pnat\n')

            # Restart bluetooth with new configuration
            subprocess.run(['systemctl', 'start', 'bluetooth'], check=True)
            time.sleep(2)

            # Verify bluetooth is running
            result = subprocess.run(['systemctl', 'is-active', 'bluetooth'], 
                                 capture_output=True, text=True)
            if result.stdout.strip() != "active":
                raise Exception("Failed to start bluetooth service")

            # Add current user to bluetooth group
            username = os.getenv('SUDO_USER', os.getenv('USER'))
            if username:
                subprocess.run(['usermod', '-a', '-G', 'bluetooth', username], 
                             check=True)

        except Exception as e:
            logger.error(f"Bluetooth configuration failed: {str(e)}")
            raise

    def _cleanup_existing_service(self):
        """Clean up any existing D-Bus service registrations."""
        try:
            subprocess.run(['systemctl', 'restart', 'dbus'], check=True)
            time.sleep(1)
            subprocess.run(['systemctl', 'restart', 'bluetooth'], check=True)
            time.sleep(2)
        except Exception as e:
            logger.error(f"Service cleanup failed: {str(e)}")