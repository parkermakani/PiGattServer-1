import asyncio
from dbus_next.aio import MessageBus
from dbus_next import BusType
from service_definitions import ServiceDefinitions, CharacteristicProperties
from logger_config import logger
from utils import check_bluetooth_status

class BLEGattServer:
    def __init__(self):
        """Initialize BLE GATT Server."""
        self.bus = None
        self.adapter = None
        self.advertisement = None
        self.service = None

    async def setup_dbus(self):
        """Setup D-Bus connection and get BlueZ interface."""
        self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        introspection = await self.bus.introspect('org.bluez', '/org/bluez')
        obj = self.bus.get_proxy_object('org.bluez', '/org/bluez', introspection)
        self.adapter = obj.get_interface('org.bluez.Adapter1')

    async def start_advertising(self):
        """Start BLE advertising."""
        try:
            await self.adapter.call_set_powered(True)
            logger.info("Bluetooth adapter powered on")

            # Register GATT service
            path = '/org/bluez/example/service0'
            await self.bus.request_name('org.bluez.example')
            
            # Set discoverable
            await self.adapter.call_set_discoverable(True)
            await self.adapter.call_set_pairable(True)
            
            logger.info("Started advertising GATT service")
            
            # Keep the server running
            while True:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"Error in GATT server: {str(e)}")
            raise
        finally:
            if self.adapter:
                try:
                    await self.adapter.call_set_discoverable(False)
                    await self.adapter.call_set_pairable(False)
                except:
                    pass
            logger.info("GATT server stopped")

async def main():
    """Main function to run the GATT server."""
    if not check_bluetooth_status():
        logger.error("Bluetooth is not available or not enabled")
        return

    server = BLEGattServer()
    try:
        await server.setup_dbus()
        await server.start_advertising()
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
