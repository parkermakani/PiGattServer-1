#!/usr/bin/env python3
import os
import shutil
import subprocess
from logger_config import logger

def install_service():
    """Install the BLE GATT server as a systemd service."""
    try:
        # Create installation directory
        install_dir = '/opt/pigattserver'
        os.makedirs(install_dir, exist_ok=True)
        
        # List of files to copy
        files_to_copy = [
            'ble_server.py',
            'service_definitions.py',
            'utils.py',
            'logger_config.py',
            'mock_dbus.py',
            'bluez-config.conf',
            'setup_bluetooth.py'  # Added setup_bluetooth.py to the list
        ]
        
        # Copy files to installation directory
        for file in files_to_copy:
            if os.path.exists(file):
                shutil.copy2(file, os.path.join(install_dir, file))
                logger.info(f"Copied {file} to {install_dir}")
            else:
                logger.error(f"Required file {file} not found")
                return False
        
        # Copy and install systemd service file
        service_file = 'pigattserver.service'
        systemd_dir = '/etc/systemd/system'
        if os.path.exists(service_file):
            shutil.copy2(service_file, os.path.join(systemd_dir, service_file))
            logger.info(f"Installed {service_file} to {systemd_dir}")
        else:
            logger.error(f"Required file {service_file} not found")
            return False

        # Install D-Bus configuration file
        dbus_conf_file = 'org.bluez.pigattserver.conf'
        dbus_conf_dir = '/etc/dbus-1/system.d'
        if os.path.exists(dbus_conf_file):
            os.makedirs(dbus_conf_dir, exist_ok=True)
            shutil.copy2(dbus_conf_file, os.path.join(dbus_conf_dir, dbus_conf_file))
            logger.info(f"Installed {dbus_conf_file} to {dbus_conf_dir}")
            
            # Reload D-Bus configuration
            subprocess.run(['systemctl', 'reload', 'dbus'], check=True)
            logger.info("Reloaded D-Bus configuration")
            
            # Reload systemd daemon
            subprocess.run(['systemctl', 'daemon-reload'], check=True)
            logger.info("Reloaded systemd daemon")
            
            # Enable and start the service
            subprocess.run(['systemctl', 'enable', 'pigattserver'], check=True)
            logger.info("Enabled pigattserver service")
            
            subprocess.run(['systemctl', 'start', 'pigattserver'], check=True)
            logger.info("Started pigattserver service")
            
            return True
        else:
            logger.error(f"Required file {dbus_conf_file} not found")
            return False
            
    except Exception as e:
        logger.error(f"Error installing service: {str(e)}")
        return False

if __name__ == "__main__":
    if os.geteuid() != 0:
        logger.error("This script must be run as root")
        exit(1)
    
    if install_service():
        logger.info("Service installation completed successfully")
    else:
        logger.error("Service installation failed")
        exit(1)
