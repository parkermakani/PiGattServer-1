#!/usr/bin/env python3

import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
import logging
import sys
import os
from datetime import datetime
from gi.repository import GLib

# Set up logging configuration
def setup_logging():
    # Create logs directory if it doesn't exist
    log_dir = "/var/log/pigattserver"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # Set up file for logging
    log_file = os.path.join(log_dir, "pigattserver.log")

    # Create a logger
    logger = logging.getLogger('ble_server')
    logger.setLevel(logging.DEBUG)

    # Create handlers
    file_handler = logging.FileHandler(log_file)
    console_handler = logging.StreamHandler(sys.stdout)

    # Create formatters and add it to handlers
    log_format = logging.Formatter(
        '%(asctime)s - %(name)s - [%(levelname)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(log_format)
    console_handler.setFormatter(log_format)

    # Add handlers to the logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

class GATTCharacteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            'org.bluez.GattCharacteristic1': {
                'Service': self.service.get_path(),
                'UUID': self.uuid,
                'Flags': self.flags,
            }
        }

    @dbus.service.method('org.freedesktop.DBus.Properties',
                        in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != 'org.bluez.GattCharacteristic1':
            raise dbus.exceptions.DBusException(
                'org.bluez.Error.InvalidArgs',
                'Interface {} not supported'.format(interface))
        return self.get_properties()['org.bluez.GattCharacteristic1']

class GATTService(dbus.service.Object):
    PATH_BASE = '/org/bluez/example/service'

    def __init__(self, bus, index, uuid, primary):
        self.path = self.PATH_BASE + str(index)
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

    @dbus.service.method('org.freedesktop.DBus.Properties',
                        in_signature='s',
                        out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != 'org.bluez.GattService1':
            raise dbus.exceptions.DBusException(
                'org.bluez.Error.InvalidArgs',
                'Interface {} not supported'.format(interface))
        return self.get_properties()['org.bluez.GattService1']

class BLEGATTServer(dbus.service.Object):
    def __init__(self, bus, adapter_name, logger):
        self.path = '/org/bluez/example'
        self.logger = logger
        self.services = []
        self.adapter_name = adapter_name
        self.bus = bus
        super().__init__(bus, self.path)

        self._setup_dbus()
        self._add_service()

    def _add_service(self):
        """Add a test service"""
        service = GATTService(self.bus, 0, 
                            '12345678-1234-5678-1234-56789abcdef0', True)
        self.services.append(service)

        # Add a test characteristic
        char = GATTCharacteristic(self.bus, 0,
                                '12345678-1234-5678-1234-56789abcdef1',
                                ['read', 'write'], service)
        service.add_characteristic(char)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def _setup_dbus(self):
        try:
            self.logger.debug("Setting up D-Bus interfaces")
            adapter_path = f'/org/bluez/{self.adapter_name}'
            adapter = self.bus.get_object('org.bluez', adapter_path)

            adapter_props = dbus.Interface(adapter, 'org.freedesktop.DBus.Properties')

            if not adapter_props.Get('org.bluez.Adapter1', 'Powered'):
                adapter_props.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(1))

            self.ad_manager = dbus.Interface(adapter, 'org.bluez.LEAdvertisingManager1')
            self.service_manager = dbus.Interface(adapter, 'org.bluez.GattManager1')

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
            self.service_manager.RegisterApplication(self.get_path(), {})
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