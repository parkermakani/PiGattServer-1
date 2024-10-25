# setup_bluetooth.py

import subprocess
import os
from logger_config import logger

def setup_bluetooth_permissions():
    """Setup Bluetooth permissions and configuration."""
    try:
        # Update BlueZ configuration
        bluez_config = """
[General]
Name = PiGattServer
Class = 0x000000
DiscoverableTimeout = 0
PairableTimeout = 0
Privacy = 0x00
JustWorksRepairing = always
DisablePlugins = pnat

[Policy]
AutoEnable=true
"""
        # Write configuration directly instead of copying a file
        try:
            with open('/etc/bluetooth/main.conf', 'w') as f:
                f.write(bluez_config)
            logger.info("BlueZ configuration updated successfully")
        except Exception as e:
            logger.error(f"Failed to write BlueZ configuration: {str(e)}")
            return False

        # Restart bluetooth service
        subprocess.run(['systemctl', 'restart', 'bluetooth'], check=True)
        logger.info("Bluetooth service restarted successfully")

        # Wait for bluetooth service to be fully up
        time.sleep(2)

        # Add current user to bluetooth group
        current_user = os.getenv('SUDO_USER', os.getenv('USER'))
        subprocess.run(['usermod', '-a', '-G', 'bluetooth', current_user], check=True)
        logger.info(f"Added user {current_user} to bluetooth group")

        # Set capabilities for Python
        python_path = subprocess.check_output(['which', 'python3']).decode().strip()
        subprocess.run(['setcap', 'cap_net_raw,cap_net_admin+eip', python_path], check=True)
        logger.info("Set required capabilities for Python")

        # Reset hci0 interface
        subprocess.run(['hciconfig', 'hci0', 'down'], check=True)
        subprocess.run(['hciconfig', 'hci0', 'up'], check=True)
        logger.info("Reset Bluetooth interface")

        return True

    except Exception as e:
        logger.error(f"Failed to setup Bluetooth permissions: {str(e)}")
        return False