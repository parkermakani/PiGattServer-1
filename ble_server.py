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

#!/usr/bin/env python3

# ... (keep your existing imports and logging setup)

class Application(dbus.service.Object):
    def __init__(self, bus):
        self.path = '/org/bluez/example'
        self.services = []
        self.bus = bus
        super().__init__(bus, self.path)
        self._logger = logging.getLogger('ble_server')

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        self._logger.debug(f'Adding service: {service.get_path()}')
        self.services.append(service)
        # No need to reinitialize the service as it's already initialized

    @dbus.service.method(DBUS_OM_IFACE, out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        response = {}
        self._logger.debug('GetManagedObjects called')

        for service in self.services:
            response[service.get_path()] = service.get_properties()
            chrcs = service.get_characteristics()
            for chrc in chrcs:
                response[chrc.get_path()] = chrc.get_properties()

        self._logger.debug(f'GetManagedObjects response: {response}')
        return response

class Service(dbus.service.Object):
    PATH_BASE = '/org/bluez/example/service'

    def __init__(self, bus, index, uuid, primary):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        self._logger = logging.getLogger('ble_server')
        self._logger.debug(f'Service initialized: {self.path}')
        super().__init__(bus, self.path)

    def add_characteristic(self, characteristic):
        self._logger.debug(f'Adding characteristic: {characteristic.get_path()}')
        self.characteristics.append(characteristic)

class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + '/char' + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.value = []
        self._logger = logging.getLogger('ble_server')
        self._logger.debug(f'Characteristic initialized: {self.path}')
        super().__init__(bus, self.path)

class SITRService(Service):
    SITR_UUID = '12345678-1234-5678-1234-56789abcdef0'

    def __init__(self, bus, index):
        super().__init__(bus, index, self.SITR_UUID, True)
        self.add_characteristic(SITRCharacteristic(bus, 0, self))

class SITRCharacteristic(Characteristic):
    SITR_CHARACTERISTIC_UUID = '12345678-1234-5678-1234-56789abcdef1'

    def __init__(self, bus, index, service):
        super().__init__(
            bus, index,
            self.SITR_CHARACTERISTIC_UUID,
            ['read', 'write'],
            service)

def main():
    logger = logging.getLogger('ble_server')

    try:
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
            error_handler=lambda error: logger.error(f'Failed to register advertisement: {str(error)}'))
        logger.info('Advertisement registered')

        logger.debug('Registering application...')
        service_manager.RegisterApplication(
            app.get_path(), {},
            error_handler=lambda error: logger.error(f'Failed to register application: {str(error)}'))
        logger.info('Application registered')

        logger.info('GATT server is running. Press Ctrl+C to stop.')

        try:
            mainloop.run()
        except KeyboardInterrupt:
            logger.info('Shutting down GATT server')
            ad_manager.UnregisterAdvertisement(advertisement.get_path())
            service_manager.UnregisterApplication(app.get_path())
            logger.info('Server stopped')

    except Exception as e:
        logger.error(f'Fatal error: {str(e)}')
        logger.debug('Exception details:', exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()