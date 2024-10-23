import logging
import sys

def setup_logger():
    """Configure logging for the BLE server application."""
    logger = logging.getLogger('ble_server')
    logger.setLevel(logging.INFO)

    # Create console handler with formatting
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    
    # Add handler to logger
    logger.addHandler(console_handler)
    
    return logger

# Create and configure logger
logger = setup_logger()
