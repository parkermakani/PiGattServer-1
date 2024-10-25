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
BASE_PATH = '/org/bluez/pigattserver'

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

class BLEService(dbus.service.Object):
    """Base BLE service class with D-Bus support"""
    
    def __init__(self, bus, index, uuid, primary=True):
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        self.path = f'{BASE_PATH}/service{index}'
        logger.debug(f'Service path: {self.path}')
        super().__init__(bus, self.path)

    def get_properties(self):
        """Get the D-Bus properties for this service"""
        return {
            GATT_SERVICE_IFACE: {
                'UUID': self.uuid,
                'Primary': self.primary,
                'Characteristics': dbus.Array(
                    self.get_characteristic_paths(),
                    signature='o')
            }
        }

    def get_path(self):
        """Get the D-Bus object path"""
        return dbus.ObjectPath(self.path)

    def get_characteristic_paths(self):
        """Get the D-Bus object paths of all characteristics"""
        return [char.get_path() for char in self.characteristics]

    def add_characteristic(self, characteristic):
        """Add a characteristic to this service"""
        logger.debug('Adding characteristic')
        self.characteristics.append(characteristic)
        characteristic.service = self
        logger.debug('Characteristic added')

    @dbus.service.method(DBUS_PROP_IFACE,
                        in_signature='s',
                        out_signature='a{sv}')
    def GetAll(self, interface):
        """Get all D-Bus properties for the specified interface"""
        if interface != GATT_SERVICE_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_SERVICE_IFACE]

class BLECharacteristic(dbus.service.Object):
    """Base BLE characteristic class with D-Bus support"""
    
    def __init__(self, bus, index, uuid, flags, service):
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.notifying = False
        self.value = dbus.Array([], signature='y')
        self.path = f'{service.path}/char{index}'
        logger.debug(f'Characteristic path: {self.path}')
        super().__init__(bus, self.path)

    def get_properties(self):
        """Get the D-Bus properties for this characteristic"""
        return {
            GATT_CHRC_IFACE: {
                'Service': self.service.get_path(),
                'UUID': self.uuid,
                'Flags': self.flags,
                'Value': self.value,
                'Notifying': dbus.Boolean(self.notifying)
            }
        }

    def get_path(self):
        """Get the D-Bus object path"""
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE,
                        in_signature='s',
                        out_signature='a{sv}')
    def GetAll(self, interface):
        """Get all D-Bus properties for the specified interface"""
        if interface != GATT_CHRC_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_CHRC_IFACE]

    @dbus.service.method(GATT_CHRC_IFACE,
                        in_signature='ay',
                        out_signature='ay')
    def ReadValue(self, options):
        """Read the characteristic value"""
        logger.debug('ReadValue called')
        return self.value

    @dbus.service.method(GATT_CHRC_IFACE,
                        in_signature='aya{sv}')
    def WriteValue(self, value, options):
        """Write the characteristic value"""
        logger.debug(f'WriteValue called with: {bytes(value)}')
        self.value = value

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self):
        """Start notifications for this characteristic"""
        if not self.notifying:
            self.notifying = True
            logger.debug('Notifications enabled')

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self):
        """Stop notifications for this characteristic"""
        if self.notifying:
            self.notifying = False
            logger.debug('Notifications disabled')

class SITRCharacteristic(BLECharacteristic):
    """SITR specific characteristic"""
    SITR_CHARACTERISTIC_UUID = '12345678-1234-5678-1234-56789abcdef1'

    def __init__(self, bus, index, service):
        logger.debug('Initializing SITR characteristic')
        super().__init__(
            bus, index,
            self.SITR_CHARACTERISTIC_UUID,
            ['read', 'write', 'notify'],
            service)

class SITRService(BLEService):
    """SITR specific service"""
    SITR_UUID = '12345678-1234-5678-1234-56789abcdef0'

    def __init__(self, bus, index):
        logger.debug('Initializing SITR service')
        super().__init__(bus, index, self.SITR_UUID, True)
        self.add_characteristic(SITRCharacteristic(bus, 0, self))

class Application(dbus.service.Object):
    """BLE GATT Application"""
    
    def __init__(self, bus):
        self.path = f'{BASE_PATH}'
        self.services = []
        super().__init__(bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        logger.debug('Adding service')
        self.services.append(service)
        logger.debug('Service added')

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
    """BLE Advertisement"""
    
    def __init__(self, bus, index, advertising_type):
        self.path = f'{BASE_PATH}/advertisement{index}'
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
    """Find the Bluetooth adapter"""
    remote_om = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, '/'),
                              DBUS_OM_IFACE)
    objects = remote_om.GetManagedObjects()

    for path, interfaces in objects.items():
        if GATT_MANAGER_IFACE in interfaces:
            return bus.get_object(BLUEZ_SERVICE_NAME, path)

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

        # Create and add service
        app.add_service(SITRService(bus, 0))

        mainloop = GLib.MainLoop()

        logger.debug('Registering advertisement...')
        ad_manager.RegisterAdvertisement(
            advertisement.get_path(), {},
            reply_handler=lambda: logger.info('Advertisement registered'),
            error_handler=lambda error: logger.error(f'Failed to register advertisement: {str(error)}'))

        logger.debug('Registering application...')
        service_manager.RegisterApplication(
            app.get_path(), {},
            reply_handler=lambda: logger.info('Application registered'),
            error_handler=lambda error: logger.error(f'Failed to register application: {str(error)}'))

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
