# ble_server.py

import asyncio
import dbus
import dbus.mainloop.glib
from gi.repository import GLib
import os
import subprocess
import time
import sys
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

    @staticmethod
    def verify_dependencies():
        """Verify and install required system dependencies."""
        try:
            # Check for required packages
            packages = ['bluetooth', 'bluez', 'python3-dbus', 'python3-gi']
            to_install = []

            for pkg in packages:
                result = subprocess.run(['dpkg', '-s', pkg], 
                                     capture_output=True, 
                                     text=True)
                if result.returncode != 0:
                    to_install.append(pkg)

            if to_install:
                logger.info(f"Installing missing packages: {', '.join(to_install)}")
                subprocess.run(['apt-get', 'update'], check=True)
                subprocess.run(['apt-get', 'install', '-y'] + to_install, check=True)

            return True
        except Exception as e:
            logger.error(f"Failed to verify dependencies: {str(e)}")
            return False

    @staticmethod
    def setup_permissions():
        """Setup required system permissions and configurations."""
        try:
            # Configure bluetooth service
            bt_conf = """
[General]
Name = PiGattServer
Class = 0x000000
DiscoverableTimeout = 0
PairableTimeout = 0
Privacy = 0x00
JustWorksRepairing = always

[Policy]
AutoEnable=true
"""
            with open('/etc/bluetooth/main.conf', 'w') as f:
                f.write(bt_conf)

            # Set capabilities for Python
            python_path = sys.executable
            subprocess.run(['setcap', 'cap_net_raw,cap_net_admin+eip', python_path], 
                         check=True)

            # Add current user to bluetooth group
            current_user = os.getenv('SUDO_USER', os.getenv('USER'))
            if current_user:
                subprocess.run(['usermod', '-a', '-G', 'bluetooth', current_user], 
                             check=True)

            # Reset and configure Bluetooth interface
            commands = [
                ['systemctl', 'stop', 'bluetooth'],
                ['rm', '-rf', '/var/lib/bluetooth/*'],
                ['systemctl', 'start', 'bluetooth'],
                ['systemctl', 'daemon-reload'],
                ['hciconfig', 'hci0', 'down'],
                ['hciconfig', 'hci0', 'up'],
                ['hciconfig', 'hci0', 'piscan'],
                ['bluetoothctl', 'power', 'on'],
                ['bluetoothctl', 'discoverable', 'on'],
                ['bluetoothctl', 'pairable', 'on']
            ]

            for cmd in commands:
                subprocess.run(cmd, check=True)
                time.sleep(0.5)

            return True

        except Exception as e:
            logger.error(f"Failed to setup permissions: {str(e)}")
            return False

    def initialize(self):
        """Initialize the BLE GATT server with proper setup."""
        try:
            # Verify running as root
            if os.geteuid() != 0:
                raise Exception("This script must be run as root")

            # Check and install dependencies
            if not self.verify_dependencies():
                raise Exception("Failed to verify dependencies")

            # Setup permissions and configurations
            if not self.setup_permissions():
                raise Exception("Failed to setup permissions")

            # Initialize D-Bus
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            self.bus = dbus.SystemBus()
            self.mainloop = GLib.MainLoop()

            # Get adapter object
            adapter_path = '/org/bluez/hci0'
            adapter_obj = self.bus.get_object('org.bluez', adapter_path)

            # Initialize interfaces
            self.adapter = dbus.Interface(adapter_obj, 'org.bluez.Adapter1')
            self.adapter_props = dbus.Interface(adapter_obj, 'org.freedesktop.DBus.Properties')
            self.gatt_manager = dbus.Interface(adapter_obj, 'org.bluez.GattManager1')
            self.ad_manager = dbus.Interface(adapter_obj, 'org.bluez.LEAdvertisingManager1')

            # Configure adapter
            props = {
                'Powered': dbus.Boolean(True),
                'Discoverable': dbus.Boolean(True),
                'DiscoverableTimeout': dbus.UInt32(0),
                'Pairable': dbus.Boolean(True)
            }

            for key, value in props.items():
                self.adapter_props.Set('org.bluez.Adapter1', key, value)

            return True

        except Exception as e:
            logger.error(f"Initialization failed: {str(e)}")
            return False

def main():
    """Main entry point with proper error handling."""
    try:
        server = BLEGATTServer()

        if not server.initialize():
            logger.error("Failed to initialize BLE GATT server")
            sys.exit(1)

        logger.info("Starting BLE GATT server...")
        server.run()

    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
    finally:
        if hasattr(server, 'cleanup'):
            server.cleanup()

if __name__ == "__main__":
    main()