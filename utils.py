import platform
import subprocess
from logger_config import logger

def check_bluetooth_status():
    """Check if Bluetooth is available and enabled."""
    try:
        if platform.system() != "Linux":
            logger.error("This application is designed to run on Linux/Raspberry Pi")
            return False
            
        # Check if Bluetooth service is running
        result = subprocess.run(['systemctl', 'is-active', 'bluetooth'], 
                              capture_output=True, text=True)
        
        if result.stdout.strip() != "active":
            logger.error("Bluetooth service is not running")
            return False
            
        return True
        
    except Exception as e:
        logger.error(f"Error checking Bluetooth status: {str(e)}")
        return False

def validate_characteristic_value(value):
    """Validate characteristic value before updating."""
    if not isinstance(value, (bytes, bytearray)):
        raise ValueError("Characteristic value must be bytes or bytearray")
    return True
