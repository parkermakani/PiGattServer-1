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

class BLEGATTServer(dbus.service.Object):
    def __init__(self, bus, adapter_name, logger):
        self.logger = logger
        self.path = '/org/bluez/example/service'
        self.bus = bus
        self.adapter = adapter_name

        self.logger.info(f"Initializing BLE GATT Server with adapter: {adapter_name}")
        super().__init__(bus, self.path)

        self._setup_dbus()

    def _setup_dbus(self):
        """Initialize D-Bus interface and setup required services"""
        try:
            self.logger.debug("Setting up D-Bus interfaces")

            # Get the system bus
            self.bus = dbus.SystemBus()
            self.logger.debug("Successfully connected to system bus")

            # Get the BLE controller
            adapter_path = f'/org/bluez/{self.adapter}'
            self.logger.debug(f"Attempting to get adapter at path: {adapter_path}")

            adapter = self.bus.get_object('org.bluez', adapter_path)
            adapter_props = dbus.Interface(adapter, 'org.freedesktop.DBus.Properties')

            # Power on the adapter if it's not already
            powered = adapter_props.Get('org.bluez.Adapter1', 'Powered')
            self.logger.info(f"Current adapter power state: {'On' if powered else 'Off'}")

            if not powered:
                self.logger.info("Powering on Bluetooth adapter")
                adapter_props.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(1))
                self.logger.info("Bluetooth adapter powered on successfully")

            # Set up advertisement and GATT manager
            self.logger.debug("Setting up advertisement manager")
            self.ad_manager = dbus.Interface(adapter, 'org.bluez.LEAdvertisingManager1')

            self.logger.debug("Setting up GATT manager")
            self.service_manager = dbus.Interface(adapter, 'org.bluez.GattManager1')

            self.logger.info("D-Bus setup completed successfully")

        except dbus.exceptions.DBusException as e:
            self.logger.error(f"D-Bus setup failed: {str(e)}")
            self.logger.debug(f"D-Bus exception details: {type(e).__name__}", exc_info=True)
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error during D-Bus setup: {str(e)}")
            self.logger.debug("Exception details:", exc_info=True)
            raise

    def start(self):
        """Start the GATT server"""
        try:
            self.logger.info("Starting GATT server")

            # Register GATT services
            self.logger.debug("Registering GATT application")
            self.service_manager.RegisterApplication(self.get_path(), {})
            self.logger.info("GATT application registered successfully")

            # Start advertising
            self.logger.debug("Registering advertisement")
            self.ad_manager.RegisterAdvertisement(self.get_path(), {})
            self.logger.info("Advertisement registered successfully")

        except dbus.exceptions.DBusException as e:
            self.logger.error(f"Failed to start GATT server: {str(e)}")
            self.logger.debug("D-Bus exception details:", exc_info=True)
            raise
        except Exception as e:
            self.logger.error(f"Unexpected error while starting GATT server: {str(e)}")
            self.logger.debug("Exception details:", exc_info=True)
            raise

    def stop(self):
        """Stop the GATT server"""
        try:
            self.logger.info("Stopping GATT server")

            self.logger.debug("Unregistering advertisement")
            self.ad_manager.UnregisterAdvertisement(self.get_path())
            self.logger.info("Advertisement unregistered successfully")

            self.logger.debug("Unregistering GATT application")
            self.service_manager.UnregisterApplication(self.get_path())
            self.logger.info("GATT application unregistered successfully")

        except dbus.exceptions.DBusException as e:
            self.logger.error(f"Failed to stop GATT server: {str(e)}")
            self.logger.debug("D-Bus exception details:", exc_info=True)
        except Exception as e:
            self.logger.error(f"Unexpected error while stopping GATT server: {str(e)}")
            self.logger.debug("Exception details:", exc_info=True)

def main():
    # Initialize logging
    logger = setup_logging()
    logger.info("Starting BLE GATT Server application")

    try:
        # Initialize the DBus mainloop
        logger.debug("Initializing D-Bus main loop")
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

        # Get the system bus
        logger.debug("Connecting to system bus")
        bus = dbus.SystemBus()

        # Find the first available Bluetooth adapter
        adapter_name = 'hci0'
        logger.info(f"Using Bluetooth adapter: {adapter_name}")

        # Create and initialize the GATT server
        server = BLEGATTServer(bus, adapter_name, logger)
        server.start()
        logger.info("BLE GATT Server initialized and started successfully")

        # Start the main loop
        logger.debug("Starting main event loop")
        mainloop = GLib.MainLoop()

        # Set up signal handlers
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