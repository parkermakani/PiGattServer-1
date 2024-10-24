import asyncio
from logger_config import logger
from utils import check_bluetooth_status
import os
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import time
import threading
import json
import subprocess
from functools import wraps

# Import mock D-Bus for development mode
if "REPL_ID" in os.environ:
    from mock_dbus import MockMessageBus
    logger.info("Using Mock D-Bus implementation for development")
else:
    logger.info("Using dbus-python implementation")

from service_definitions import ServiceDefinitions, CharacteristicProperties

class BLEGATTServer:
    def register_service(self):
        """Register GATT service and characteristics with improved reliability."""
        try:
            if self.is_development:
                logger.info("Development mode: Simulating service registration")
                return True

            self.service = GattService(self.bus, 0, ServiceDefinitions.CUSTOM_SERVICE_UUID)

            characteristics = [
                ('temperature', CharacteristicProperties.TEMPERATURE),
                ('humidity', CharacteristicProperties.HUMIDITY),
                ('status', CharacteristicProperties.STATUS),
                ('new_char', CharacteristicProperties.NEW_CHARACTERISTIC)  # Added new characteristic
            ]

            for idx, (name, props) in enumerate(characteristics):
                char = GattCharacteristic(
                    self.bus,
                    idx,
                    props['uuid'],
                    props['properties'],
                    self.service
                )
                self.service.add_characteristic(char)
                logger.info(f"Registered characteristic: {name} at {char.path}")

            # Register the service with BlueZ
            try:
                self.bus.export(self.service.path, self.service)
                logger.info("Service and characteristics registered successfully")
                return True
            except Exception as e:
                logger.error(f"Failed to register service: {str(e)}")
                self._cleanup_service()
                raise

        except Exception as e:
            logger.error(f"Error during service registration: {str(e)}")
            return False

    def _cleanup_service(self):
        """Clean up service registration."""
        try:
            if hasattr(self, 'service'):
                self.bus.unexport(self.service.path)
        except Exception as e:
            logger.error(f"Error during service cleanup: {str(e)}")
