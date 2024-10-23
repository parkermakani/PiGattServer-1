import os
import subprocess
from logger_config import logger

def setup_bluetooth_permissions():
    """
    Setup BlueZ permissions and configuration for the GATT server.
    This function is meant to run on actual Raspberry Pi hardware.
    """
    try:
        # Check if running in development mode
        if "REPL_ID" in os.environ:
            logger.info("Development mode: Simulating Bluetooth setup")
            logger.info("Note: Actual setup will be performed on Raspberry Pi hardware")
            return True

        # Check if running with sufficient privileges
        if os.geteuid() != 0:
            logger.error("This script needs to be run with sudo privileges")
            return False

        # Copy BlueZ configuration
        try:
            subprocess.run(['cp', 'bluez-config.conf', '/etc/bluetooth/main.conf'], check=True)
            logger.info("BlueZ configuration updated successfully")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to update BlueZ configuration: {str(e)}")
            return False

        # Restart Bluetooth service
        try:
            subprocess.run(['systemctl', 'restart', 'bluetooth'], check=True)
            logger.info("Bluetooth service restarted successfully")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to restart Bluetooth service: {str(e)}")
            return False

        # Add current user to bluetooth group
        try:
            username = os.environ.get('USER', os.environ.get('USERNAME'))
            if username:
                subprocess.run(['usermod', '-a', '-G', 'bluetooth', username], check=True)
                logger.info(f"Added user {username} to bluetooth group")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to add user to bluetooth group: {str(e)}")
            return False

        logger.info("Bluetooth permissions and configuration setup completed successfully")
        return True

    except Exception as e:
        logger.error(f"Error during Bluetooth setup: {str(e)}")
        return False

if __name__ == "__main__":
    setup_bluetooth_permissions()
