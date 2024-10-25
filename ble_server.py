#!/usr/bin/env python3

import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
import logging
import sys
import os
import subprocess
from datetime import datetime
from gi.repository import GLib

def setup_logging():
    log_dir = "/var/log/pigattserver"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    log_file = os.path.join(log_dir, "pigattserver.log")
    logger = logging.getLogger('ble_server')
    logger.setLevel(logging.DEBUG)
    file_handler = logging.FileHandler(log_file)
    console_handler = logging.StreamHandler(sys.stdout)
    log_format = logging.Formatter(
        '%(asctime)s - %(name)s - [%(levelname)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(log_format)
    console_handler.setFormatter(log_format)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger

def check_bluetooth_service():
    """Check if bluetooth service is running and configured properly"""
    try:
        # Check bluetooth service status
        status = subprocess.run(['systemctl', 'is-active', 'bluetooth'], 
                              capture_output=True, text=True)
        if status.stdout.strip() != 'active':
            subprocess.run(['systemctl', 'start', 'bluetooth'])
            subprocess.run(['systemctl', 'enable', 'bluetooth'])

        # Ensure bluetooth is powered on
        subprocess.run(['bluetoothctl', 'power', 'on'])
        subprocess.run(['bluetoothctl', 'discoverable', 'on'])
        return True
    except Exception as e:
        return False

class SITRService(dbus.service.Object):
    """SITR GATT Service"""

    def __init__(self, bus, index, uuid, primary='true'):
        self.path = f'/org/bluez/example/service{index}'
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        super().__init__(bus, self.path)

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

    @dbus.service.method(dbus.PROPERTIES_IFACE,
                        in_signature='s',
                        out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != 'org.bluez.GattService1':
            raise dbus.exceptions.DBusException(
                'org.bluez.Error.InvalidArgs',
                f'Interface {interface} not supported')
        return self.get_properties()['org.bluez.GattService1']

class SITRCharacteristic(dbus.service.Object):
    """SITR GATT Characteristic"""

    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.value = []
        super().__init__(bus, self.path)

    def get_properties(self):
        return {
            'org.bluez.GattCharacteristic1': {
                'Service': self.service.get_path(),
                'UUID': self.uuid,
                'Flags': self.flags,
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(dbus.PROPERTIES_IFACE,
                        in_signature='s',
                        out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != 'org.bluez.GattCharacteristic1':
            raise dbus.exceptions.DBusException(
                'org.bluez.Error.InvalidArgs',
                f'Interface {interface} not supported')
        return self.get_properties()['org.bluez.GattCharacteristic1']

    @dbus.service.method('org.bluez.GattCharacteristic1',
                        in_signature='a{sv}',
                        out_signature='ay')
    def ReadValue(self, options):
        return self.value

    @dbus.service.method('org.bluez.GattCharacteristic1',
                        in_signature='aya{sv}')
    def WriteValue(self, value, options):
        self.value = value

class BLEGATTServer(dbus.service.Object):
    """Main GATT Server class"""

    def __init__(self, bus, adapter_name, logger):
        self.path = '/org/bluez/example'
        self.logger = logger
        self.services = []
        self.adapter_name = adapter_name
        self.bus = bus
        super().__init__(bus, self.path)

        if not check_bluetooth_service():
            raise Exception("Failed to initialize Bluetooth service")

        self._setup_dbus()
        self._add_services()

    def _add_services(self):
        """Add SITR services"""
        # Main SITR service
        sitr_service = SITRService(self.bus, 0, 
                                 '12345678-1234-5678-1234-56789abcdef0')
        self.services.append(sitr_service)

        # Add test characteristic
        char = SITRCharacteristic(self.bus, 0,
                                '12345678-1234-5678-1234-56789abcdef1',
                                ['read', 'write'], 
                                sitr_service)
        sitr_service.add_characteristic(char)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def _setup_dbus(self):
        try:
            self.logger.debug("Setting up D-Bus interfaces")
            adapter_path = f'/org/bluez/{self.adapter_name}'

            # Get adapter object
            adapter = self.bus.get_object('org.bluez', adapter_path)
            self.logger.debug(f"Got adapter object at {adapter_path}")

            # Get adapter properties
            adapter_props = dbus.Interface(adapter, 'org.freedesktop.DBus.Properties')

            # Power on adapter if needed
            if not adapter_props.Get('org.bluez.Adapter1', 'Powered'):
                self.logger.debug("Powering on Bluetooth adapter")
                adapter_props.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(1))

            # Get required interfaces
            self.ad_manager = dbus.Interface(adapter, 'org.bluez.LEAdvertisingManager1')
            self.service_manager = dbus.Interface(adapter, 'org.bluez.GattManager1')
            self.logger.debug("D-Bus interfaces setup completed")

        except dbus.exceptions.DBusException as e:
            self.logger.error(f"D-Bus setup failed: {str(e)}")
            raise

    @dbus.service.method('org.freedesktop.DBus.ObjectManager',
                        out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            chrcs = service.get_characteristic_paths()
            for chrc in chrcs:
                response[chrc] = service.characteristics[0].get_properties()
        return response

    def start(self):
        try:
            self.logger.info("Starting GATT server")
            # Set longer timeout for registration
            self.service_manager.RegisterApplication(self.get_path(), {}, 
                                                  timeout=30000)
            self.logger.info("GATT application registered successfully")

        except dbus.exceptions.DBusException as e:
            self.logger.error(f"Failed to start GATT server: {str(e)}")
            raise

    def stop(self):
        try:
            self.logger.info("Stopping GATT server")
            self.service_manager.UnregisterApplication(self.get_path())
            self.logger.info("GATT application unregistered successfully")

        except dbus.exceptions.DBusException as e:
            self.logger.error(f"Failed to stop GATT server: {str(e)}")

def main():
    logger = setup_logging()
    logger.info("Starting BLE GATT Server application")

    try:
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SystemBus()
        adapter_name = 'hci0'

        server = BLEGATTServer(bus, adapter_name, logger)
        server.start()

        mainloop = GLib.MainLoop()

        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}")
            server.stop()
            mainloop.quit()

        import signal
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        logger.info("Server is running. Press Ctrl+C to stop.")
        mainloop.run()

    except Exception as e:
        logger.error(f"Fatal error in main: {str(e)}")
        logger.debug("Exception details:", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()