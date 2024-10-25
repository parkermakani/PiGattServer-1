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

# Constants
BLUEZ_SERVICE_NAME = 'org.bluez'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHRC_IFACE = 'org.bluez.GattCharacteristic1'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'

# Set up logging
logger = logging.getLogger('ble_server')
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - [%(levelname)s] - %(message)s', 
                            datefmt='%Y-%m-%d %H:%M:%S')
handler.setFormatter(formatter)
logger.addHandler(handler)

class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.freedesktop.DBus.Error.InvalidArgs'

class NotSupportedException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.bluez.Error.NotSupported'

class Characteristic:
    """Base characteristic class"""
    def __init__(self, uuid, flags=['read']):
        self.uuid = uuid
        self.flags = flags
        self.path = None
        self.service = None
        self.value = []

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        return {
            GATT_CHRC_IFACE: {
                'Service': self.service.get_path(),
                'UUID': self.uuid,
                'Flags': self.flags,
                'Value': self.value
            }
        }

class Service:
    """Base service class"""
    PATH_BASE = '/org/bluez/example/service'

    def __init__(self, uuid, primary=True):
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        self.path = None

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        return {
            GATT_SERVICE_IFACE: {
                'UUID': self.uuid,
                'Primary': self.primary,
                'Characteristics': dbus.Array(
                    self.get_characteristic_paths(),
                    signature='o')
            }
        }

    def get_characteristic_paths(self):
        return [char.get_path() for char in self.characteristics]

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)
        characteristic.service = self

class DBusCharacteristic(dbus.service.Object, Characteristic):
    """D-Bus enabled characteristic"""
    def __init__(self, bus, index, uuid, flags, service_path):
        self.path = service_path + '/char' + str(index)
        logger.debug(f'Initializing characteristic at path: {self.path}')

        # Initialize both parent classes
        dbus.service.Object.__init__(self, bus, self.path)
        Characteristic.__init__(self, uuid, flags)

    @dbus.service.method(DBUS_PROP_IFACE,
                        in_signature='s',
                        out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != GATT_CHRC_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_CHRC_IFACE]

    @dbus.service.method(GATT_CHRC_IFACE,
                        in_signature='ay',
                        out_signature='ay')
    def ReadValue(self, options):
        logger.debug('ReadValue called')
        return self.value

    @dbus.service.method(GATT_CHRC_IFACE,
                        in_signature='aya{sv}')
    def WriteValue(self, value, options):
        logger.debug(f'WriteValue called with: {bytes(value)}')
        self.value = value

class DBusService(dbus.service.Object, Service):
    """D-Bus enabled service"""
    def __init__(self, bus, index, uuid, primary=True):
        self.path = self.PATH_BASE + str(index)
        logger.debug(f'Initializing service at path: {self.path}')

        # Initialize both parent classes
        dbus.service.Object.__init__(self, bus, self.path)
        Service.__init__(self, uuid, primary)

    @dbus.service.method(DBUS_PROP_IFACE,
                        in_signature='s',
                        out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != GATT_SERVICE_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_SERVICE_IFACE]

class SITRCharacteristic(DBusCharacteristic):
    """SITR specific characteristic"""
    def __init__(self, bus, index, service_path):
        super().__init__(
            bus, index,
            '12345678-1234-5678-1234-56789abcdef1',
            ['read', 'write'],
            service_path)

class SITRService(DBusService):
    """SITR specific service"""
    def __init__(self, bus, index):
        super().__init__(bus, index, '12345678-1234-5678-1234-56789abcdef0', True)
        self.add_characteristic(SITRCharacteristic(bus, 0, self.path))

class Application(dbus.service.Object):
    def __init__(self, bus):
        self.path = '/org/bluez/example'
        self.services = []
        super().__init__(bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        logger.debug(f'Adding service: {service.get_path()}')
        self.services.append(service)

    @dbus.service.method(DBUS_OM_IFACE,
                        out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            for char in service.characteristics:
                response[char.get_path()] = char.get_properties()
        return response

class Advertisement(dbus.service.Object):
    def __init__(self, bus, index, advertising_type):
        self.path = f'/org/bluez/example/advertisement{index}'
        self.bus = bus
        self.ad_type = advertising_type
        self.local_name = 'SITR Device'
        super().__init__(bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def get_properties(self):
        properties = dict()
        properties['Type'] = self.ad_type
        if self.local_name:
            properties['LocalName'] = dbus.String(self.local_name)
        return {LE_ADVERTISING_MANAGER_IFACE: properties}

    @dbus.service.method(DBUS_PROP_IFACE,
                        in_signature='s',
                        out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != LE_ADVERTISING_MANAGER_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[LE_ADVERTISING_MANAGER_IFACE]

def find_adapter(bus):
    remote_om = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, '/'),
                              DBUS_OM_IFACE)
    objects = remote_om.GetManagedObjects()

    for path, interfaces in objects.items():
        if GATT_MANAGER_IFACE in interfaces:
            return bus.get_object(BLUEZ_SERVICE_NAME, path)

    logger.error('Bluetooth adapter not found')
    raise Exception('Bluetooth adapter not found')

def main():
    try:
        logger.debug('Setting up DBus main loop.')
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

        logger.debug('Connecting to system bus.')
        bus = dbus.SystemBus()

        logger.debug('Finding BLE adapter...')
        adapter = find_adapter(bus)
        logger.debug('BLE adapter found.')

        logger.debug('Creating service manager and advertisement manager interfaces.')
        service_manager = dbus.Interface(adapter, GATT_MANAGER_IFACE)
        ad_manager = dbus.Interface(adapter, LE_ADVERTISING_MANAGER_IFACE)

        logger.debug('Creating advertisement and GATT application.')
        advertisement = Advertisement(bus, 0, 'peripheral')
        app = Application(bus)
        app.add_service(SITRService(bus, 0))

        mainloop = GLib.MainLoop()

        logger.debug('Registering advertisement...')
        ad_manager.RegisterAdvertisement(
            advertisement.get_path(), {},
            error_handler=lambda error: logger.error(f'Failed to register advertisement: {str(error)}'))
        logger.info('Advertisement registered')

        logger.debug('Registering application...')
        service_manager.RegisterApplication(
            app.get_path(), {},
            error_handler=lambda error: logger.error(f'Failed to register application: {str(error)}'))
        logger.info('Application registered')

        logger.info('GATT server is running. Press Ctrl+C to stop.')

        mainloop.run()

    except KeyboardInterrupt:
        logger.info('Shutting down...')
        ad_manager.UnregisterAdvertisement(advertisement.get_path())
        logger.info('Advertisement unregistered')
        sys.exit(0)
    except Exception as e:
        logger.error(f'Fatal error: {str(e)}')
        logger.debug('Exception details:', exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()