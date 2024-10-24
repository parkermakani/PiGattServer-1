from enum import Enum
import uuid
import dbus
import dbus.service
from logger_config import logger  # Make sure logger is correctly imported
from gi.repository import GLib

class ServiceDefinitions:
    """Define BLE service and characteristic UUIDs and properties."""
    
    # Custom Service UUID
    CUSTOM_SERVICE_UUID = "00000000-1111-2222-3333-444444444444"
    
    # Characteristic UUIDs
    TEMPERATURE_CHAR_UUID = "00000001-1111-2222-3333-444444444444"
    HUMIDITY_CHAR_UUID = "00000002-1111-2222-3333-444444444444"
    STATUS_CHAR_UUID = "00000003-1111-2222-3333-444444444444"
    NEW_CHAR_UUID = "0000BBBB-0000-1000-8000-00805F9B34FB"  # Standard base UUID format with 0xBBBB

class CharacteristicProperties:
    """Define characteristic properties and permissions."""
    
    TEMPERATURE = {
        "uuid": ServiceDefinitions.TEMPERATURE_CHAR_UUID,
        "properties": ["read"],
        "initial_value": bytearray([0x00])
    }
    
    HUMIDITY = {
        "uuid": ServiceDefinitions.HUMIDITY_CHAR_UUID,
        "properties": ["read"],
        "initial_value": bytearray([0x00])
    }
    
    STATUS = {
        "uuid": ServiceDefinitions.STATUS_CHAR_UUID,
        "properties": ["read"],
        "initial_value": bytearray([0x00])
    }

    NEW_CHARACTERISTIC = {
        "uuid": ServiceDefinitions.NEW_CHAR_UUID,
        "properties": ["read", "write", "notify"],
        "initial_value": bytearray([0x00])
    }

class GattService(dbus.service.Object):
    """
    GATT Service implementation using D-Bus.
    """

    def __init__(self, bus, index, uuid):
        logger.debug(f"Initializing GATT service with index {index} and UUID {uuid}")
        self.path = f'/org/bluez/pigattserver/service{index}'
        self.uuid = uuid
        self.bus = bus
        self.characteristics = []
        self.next_index = 0

        super().__init__(bus, self.path)
        logger.debug(f"GATT service created at path {self.path}")

    def get_properties(self):
        """Return the service properties dictionary."""
        logger.debug(f"Getting properties for GATT service at {self.path}")
        return {
            'org.bluez.GattService1': {
                'UUID': dbus.String(self.uuid),
                'Primary': dbus.Boolean(True),
                'Characteristics': dbus.Array(
                    self.get_characteristic_paths(),
                    signature='o'
                )
            }
        }

    def get_path(self):
        """Return the D-Bus path of the service."""
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, characteristic):
        """Add a characteristic to this service."""
        self.characteristics.append(characteristic)
        logger.debug(f"Added characteristic to service at {self.path}: {characteristic.get_path()}")

    def get_characteristic_paths(self):
        """Get the D-Bus paths of all characteristics."""
        result = []
        for chrc in self.characteristics:
            result.append(chrc.get_path())
        return result

    @dbus.service.method('org.freedesktop.DBus.Properties',
                         in_signature='s',
                         out_signature='a{sv}')
    def GetAll(self, interface):
        """Get all properties for the specified interface."""
        logger.debug(f"GetAll called for interface {interface} on service {self.path}")
        if interface != 'org.bluez.GattService1':
            raise dbus.exceptions.DBusException(
                'org.bluez.Error.InvalidArguments',
                f'Unknown interface: {interface}')

        return self.get_properties()['org.bluez.GattService1']