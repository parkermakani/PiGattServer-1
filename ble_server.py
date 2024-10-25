#!/usr/bin/env python3

import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
import logging

from gi.repository import GLib

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('ble_server')

class BLEGATTServer(dbus.service.Object):
    def __init__(self, bus, adapter_name):
        self.path = '/org/bluez/example/service'
        self.bus = bus
        self.adapter = adapter_name
        super().__init__(bus, self.path)

        self._setup_dbus()

    def _setup_dbus(self):
        """Initialize D-Bus interface and setup required services"""
        try:
            # Get the system bus
            self.bus = dbus.SystemBus()

            # Get the BLE controller
            adapter = self.bus.get_object('org.bluez', f'/org/bluez/{self.adapter}')
            adapter_props = dbus.Interface(adapter, 'org.freedesktop.DBus.Properties')

            # Power on the adapter if it's not already
            if not adapter_props.Get('org.bluez.Adapter1', 'Powered'):
                adapter_props.Set('org.bluez.Adapter1', 'Powered', dbus.Boolean(1))

            # Set up advertisement
            self.ad_manager = dbus.Interface(adapter, 'org.bluez.LEAdvertisingManager1')
            self.service_manager = dbus.Interface(adapter, 'org.bluez.GattManager1')

        except dbus.exceptions.DBusException as e:
            logger.error(f"D-Bus setup failed: {str(e)}")
            raise

def main():
    # Initialize the DBus mainloop
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    try:
        # Get the system bus
        bus = dbus.SystemBus()

        # Find the first available Bluetooth adapter
        adapter_name = 'hci0'  # This is typically the default adapter name

        # Create and initialize the GATT server
        server = BLEGATTServer(bus, adapter_name)
        logger.info("BLE GATT Server initialized successfully")

        # Start the main loop
        mainloop = GLib.MainLoop()
        mainloop.run()

    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        raise

if __name__ == '__main__':
    main()