from enum import Enum
import uuid

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
