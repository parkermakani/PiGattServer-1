import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service

from gi.repository import GLib

BLUEZ_SERVICE_NAME = 'org.bluez'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
DBUS_OM_IFACE =      'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE =    'org.freedesktop.DBus.Properties'

class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.freedesktop.DBus.Error.InvalidArgs'

class Application(dbus.service.Object):
    def __init__(self, bus):
        self.path = '/'
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        self.services.append(service)

    @dbus.service.method(DBUS_OM_IFACE, out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            chrcs = service.get_characteristics()
            for chrc in chrcs:
                response[chrc.get_path()] = chrc.get_properties()
                descs = chrc.get_descriptors()
                for desc in descs:
                    response[desc.get_path()] = desc.get_properties()
        return response

def register_app_cb():
    print('GATT application registered')

def register_app_error_cb(error):
    print('Failed to register application:', str(error))

def find_adapter(bus):
    remote_om = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, '/'),
                              DBUS_OM_IFACE)
    objects = remote_om.GetManagedObjects()

    for o, props in objects.items():
        if GATT_MANAGER_IFACE in props.keys():
            return o

    return None

def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    adapter = find_adapter(bus)
    if not adapter:
        print('GattManager1 interface not found')
        return

    service_manager = dbus.Interface(
        bus.get_object(BLUEZ_SERVICE_NAME, adapter),
        GATT_MANAGER_IFACE)

    app = Application(bus)

    mainloop = GLib.MainLoop()

    print('Registering GATT application...')

    try:
        service_manager.RegisterApplication(app.get_path(), {},
                                         reply_handler=register_app_cb,
                                         error_handler=register_app_error_cb)
    except dbus.exceptions.DBusException as e:
        print(f"Failed to register application: {str(e)}")
        print("\nDumping D-Bus connection info:")
        print(f"Bus name: {bus.get_unique_name()}")
        print(f"Adapter path: {adapter}")
        return

    try:
        mainloop.run()
    except KeyboardInterrupt:
        print("Application stopped by user")

if __name__ == '__main__':
    main()