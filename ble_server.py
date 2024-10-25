#!/usr/bin/env python3

# ... (keep your existing imports and constants)

class Characteristic:
    """Base characteristic class"""
    def __init__(self, uuid, flags=['read']):
        self.uuid = uuid
        self.flags = flags
        self.value = []
        self.path = None
        self.service = None

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
    def __init__(self, bus, index, uuid, flags, service):
        # Initialize the base characteristic first
        Characteristic.__init__(self, uuid, flags)

        # Set the path using the service's path
        self.service = service
        self.path = f"{service.get_path()}/char{index}"
        logger.debug(f'Initializing characteristic at path: {self.path}')

        # Initialize the D-Bus object
        dbus.service.Object.__init__(self, bus, self.path)

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
        # Initialize the base service first
        Service.__init__(self, uuid, primary)

        # Set the path
        self.path = f"{self.PATH_BASE}{index}"
        logger.debug(f'Initializing service at path: {self.path}')

        # Initialize the D-Bus object
        dbus.service.Object.__init__(self, bus, self.path)

    @dbus.service.method(DBUS_PROP_IFACE,
                        in_signature='s',
                        out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != GATT_SERVICE_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[GATT_SERVICE_IFACE]

class SITRCharacteristic(DBusCharacteristic):
    """SITR specific characteristic"""
    SITR_CHARACTERISTIC_UUID = '12345678-1234-5678-1234-56789abcdef1'

    def __init__(self, bus, index, service):
        super().__init__(
            bus, index,
            self.SITR_CHARACTERISTIC_UUID,
            ['read', 'write'],
            service)

class SITRService(DBusService):
    """SITR specific service"""
    SITR_UUID = '12345678-1234-5678-1234-56789abcdef0'

    def __init__(self, bus, index):
        super().__init__(bus, index, self.SITR_UUID, True)
        logger.debug(f'Creating SITR characteristic for service at {self.get_path()}')
        self.add_characteristic(SITRCharacteristic(bus, 0, self))

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

# ... (keep your existing Advertisement class and main function)