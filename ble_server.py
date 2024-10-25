#!/usr/bin/env python3

import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
import logging
import sys
import os
from gi.repository import GLib

# D-Bus Interface constants
BLUEZ_SERVICE_NAME = 'org.bluez'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
GATT_SERVICE_IFACE = 'org.bluez.GattService1'
GATT_CHRC_IFACE = 'org.bluez.GattCharacteristic1'
LE_ADVERTISING_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'

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

logger = setup_logging()

class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.freedesktop.DBus.Error.InvalidArgs'

class NotSupportedException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.bluez.Error.NotSupported'

class Advertisement(dbus.service.Object):
    PATH_BASE = '/org/bluez/example/advertisement'

    def __init__(self, bus, index, advertising_type):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = advertising_type
        self.service_uuids = None
        self.manufacturer_data = None
        self.solicit_uuids = None
        self.service_data = None
        self.local_name = 'SITR Device'
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        properties = {
            'Type': self.ad_type,
            'LocalName': dbus.String(self.local_name)
        }
        if self.service_uuids is not None:
            properties['ServiceUUIDs'] = dbus.Array(self.service_uuids, signature='s')
        if self.solicit_uuids is not None:
            properties['SolicitUUIDs'] = dbus.Array(self.solicit_uuids, signature='s')
        if self.manufacturer_data is not None:
            properties['ManufacturerData'] = dbus.Dictionary(self.manufacturer_data, signature='qv')
        if self.service_data is not None:
            properties['ServiceData'] = dbus.Dictionary(self.service_data, signature='sv')
        return {LE_ADVERTISING_MANAGER_IFACE: properties}

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != LE_ADVERTISING_MANAGER_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[LE_ADVERTISING_MANAGER_IFACE]

class Application(dbus.service.Object):
    def __init__(self, bus):
        self.bus = bus  # Store the bus in the object
        self.path = '/org/bluez/example/app'
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)

    def add_service(self, service):
        self.services.append(service)
        self.add_managed_object(service)
        logger.debug(f'Added service: {service.get_path()}')

    def add_managed_object(self, obj):
        logger.debug(f"Adding managed object: {obj.get_path()}")
        dbus.service.Object.__init__(obj, self.bus, obj.get_path())

    @dbus.service.method(DBUS_OM_IFACE, out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            logger.debug(f"Service added to GetManagedObjects: {service.get_path()}")
            for chrc in service.get_characteristics():
                response[chrc.get_path()] = chrc.get_properties()
                logger.debug(f"Characteristic added to GetManagedObjects: {chrc.get_path()}")
        logger.debug(f'GetManagedObjects response: {response}')
        return response

class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.value = []
        dbus.service.Object.__init__(self, bus, self.path)
        logger.debug(f'Characteristic initialized: {self.get_path()}')

    def get_properties(self):
        return {
            GATT_CHRC_IFACE: {
                'Service': self.service.get_path(),
                'UUID': self.uuid,
                'Flags': self.flags,
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != GATT_CHRC_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_CHRC_IFACE]

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='ay', out_signature='ay')
    def ReadValue(self, options):
        logger.debug('ReadValue called')
        return self.value

    @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}')
    def WriteValue(self, value, options):
        logger.debug(f'WriteValue called with value: {bytes(value)}')
        self.value = value

class Service(dbus.service.Object):
    PATH_BASE = '/org/bluez/example/service'

    def __init__(self, bus, index, uuid, primary):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)
        logger.debug(f'Service initialized: {self.get_path()}')

    def get_properties(self):
        return {
            GATT_SERVICE_IFACE: {
                'UUID': self.uuid,
                'Primary': self.primary,
                'Characteristics': dbus.Array(self.get_characteristic_paths(), signature='o')
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)
        logger.debug(f'Characteristic added: {characteristic.get_path()}')

    def get_characteristic_paths(self):
        return [chrc.get_path() for chrc in self.characteristics]

    def get_characteristics(self):
        return self.characteristics

    @dbus.service.method(DBUS_PROP_IFACE, in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != GATT_SERVICE_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_SERVICE_IFACE]

class SITRService(Service):
    SITR_UUID = '12345678-1234-5678-1234-56789abcdef0'

    def __init__(self, bus, index):
        Service.__init__(self, bus, index, self.SITR_UUID, True)
        self.add_characteristic(SITRCharacteristic(bus, 0, self))

class SITRCharacteristic(Characteristic):
    SITR_CHARACTERISTIC_UUID = '12345678-1234-5678-1234-56789abcdef1'

    def __init__(self, bus, index, service):
        Characteristic.__init__(self, bus, index, self.SITR_CHARACTERISTIC_UUID, ['read', 'write'], service)

def find_adapter(bus, adapter_pattern=None):
    remote_om = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, '/'), DBUS_OM_IFACE)
    objects = remote_om.GetManagedObjects()

    for path, interfaces in objects.items():
        if GATT_MANAGER_IFACE not in interfaces:
            continue
        if adapter_pattern is None or path.endswith(adapter_pattern):
            return bus.get_object(BLUEZ_SERVICE_NAME, path)
    raise Exception('Bluetooth adapter not found')

def main():
    global mainloop

    logger.debug('Setting up DBus main loop.')
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    logger.debug('Connecting to system bus.')
    bus = dbus.SystemBus()

    logger.debug('Finding BLE adapter...')
    adapter = find_adapter(bus)
    if not adapter:
        logger.error('BLE adapter not found')
        sys.exit(1)
    logger.debug('BLE adapter found.')

    # GATT and Advertisement Manager Interfaces
    logger.debug('Creating service manager and advertisement manager interfaces.')
    service_manager = dbus.Interface(adapter, GATT_MANAGER_IFACE)
    ad_manager = dbus.Interface(adapter, LE_ADVERTISING_MANAGER_IFACE)

    # Create advertisement and application
    logger.debug('Creating advertisement and GATT application.')
    advertisement = Advertisement(bus, 0, 'peripheral')
    app = Application(bus)
    app.add_service(SITRService(bus, 0))

    # Register Advertisement
    logger.debug('Registering advertisement...')
    try:
        ad_manager.RegisterAdvertisement(
            advertisement.get_path(), {},
            error_handler=lambda error: logger.error(f'Failed to register advertisement: {str(error)}'),
            reply_handler=lambda: logger.info('Advertisement registered')
        )
    except Exception as e:
        logger.error(f'Exception during advertisement registration: {str(e)}')

    # Register Application
    logger.debug('Registering GATT application...')
    try:
        service_manager.RegisterApplication(
            app.get_path(), {},
            error_handler=lambda error: logger.error(f'Failed to register application: {str(error)}'),
            reply_handler=lambda: logger.info('Application registered')
        )
    except Exception as e:
        logger.error(f'Exception during GATT application registration: {str(e)}')

    logger.info('GATT server is running. Press Ctrl+C to stop.')

    # Start the main loop to handle the DBus events
    try:
        mainloop = GLib.MainLoop()
        mainloop.run()
    except KeyboardInterrupt:
        logger.info('Shutting down GATT server...')
        cleanup(ad_manager, advertisement, service_manager, app)
        logger.info('GATT server shut down.')
        sys.exit(0)
    except Exception as e:
        logger.error(f'Unexpected error: {str(e)}')
        cleanup(ad_manager, advertisement, service_manager, app)
        sys.exit(1)

def cleanup(ad_manager, advertisement, service_manager, app):
    logger.debug('Cleaning up resources...')
    try:
        ad_manager.UnregisterAdvertisement(advertisement.get_path())
        logger.info('Advertisement unregistered.')
    except Exception as e:
        logger.error(f'Failed to unregister advertisement: {str(e)}')

    try:
        # Remove all services from DBus manually before exiting
        for service in app.services:
            dbus.service.Object.remove_from_connection(service)
            logger.info(f'Service unregistered: {service.get_path()}')

        # Unregister the GATT application object itself
        dbus.service.Object.remove_from_connection(app)
        logger.info('GATT application unregistered.')
    except Exception as e:
        logger.error(f'Failed to unregister GATT application: {str(e)}')

if __name__ == '__main__':
    main()
