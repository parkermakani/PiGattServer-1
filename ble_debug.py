import dbus
import subprocess
from pathlib import Path
import sys

def diagnose_bluetooth_stack():
    """
    Diagnose common issues with BlueZ and D-Bus configuration
    Returns a dict with diagnostic results
    """
    results = {
        'bluez_status': False,
        'dbus_status': False,
        'permissions': False,
        'service_files': [],
        'errors': []
    }

    try:
        # Check BlueZ service status
        bluez_status = subprocess.run(
            ['systemctl', 'status', 'bluetooth'],
            capture_output=True,
            text=True
        )
        results['bluez_status'] = 'running' in bluez_status.stdout.lower()

        # Check D-Bus service
        dbus_status = subprocess.run(
            ['systemctl', 'status', 'dbus'],
            capture_output=True,
            text=True
        )
        results['dbus_status'] = 'running' in dbus_status.stdout.lower()

        # Check for bluetooth group membership
        groups_output = subprocess.run(
            ['groups'],
            capture_output=True,
            text=True
        )
        results['permissions'] = 'bluetooth' in groups_output.stdout

        # Look for relevant service files
        service_path = Path('/usr/share/dbus-1/services/')
        if service_path.exists():
            results['service_files'] = list(service_path.glob('*.service'))

    except Exception as e:
        results['errors'].append(str(e))

    return results

def fix_common_issues(diagnostic_results):
    """
    Suggest fixes based on diagnostic results
    """
    fixes = []

    if not diagnostic_results['bluez_status']:
        fixes.append("""
        BlueZ service is not running. Try:
        sudo systemctl start bluetooth
        sudo systemctl enable bluetooth
        """)

    if not diagnostic_results['dbus_status']:
        fixes.append("""
        D-Bus service is not running. Try:
        sudo systemctl start dbus
        sudo systemctl enable dbus
        """)

    if not diagnostic_results['permissions']:
        fixes.append("""
        Current user is not in the bluetooth group. Fix with:
        sudo usermod -a -G bluetooth $USER
        Then log out and log back in.
        """)

    if not diagnostic_results['service_files']:
        fixes.append("""
        No D-Bus service files found. Ensure BlueZ is properly installed:
        sudo apt install bluez
        sudo apt install python3-dbus
        """)

    return fixes

def main():
    print("Running BLE GATT Server diagnostics...")
    results = diagnose_bluetooth_stack()

    print("\nDiagnostic Results:")
    print(f"BlueZ Service Status: {'Running' if results['bluez_status'] else 'Not Running'}")
    print(f"D-Bus Service Status: {'Running' if results['dbus_status'] else 'Not Running'}")
    print(f"Bluetooth Permissions: {'OK' if results['permissions'] else 'Missing'}")
    print("\nFound Service Files:")
    for service_file in results['service_files']:
        print(f"  - {service_file}")

    if results['errors']:
        print("\nErrors encountered:")
        for error in results['errors']:
            print(f"  - {error}")

    fixes = fix_common_issues(results)
    if fixes:
        print("\nSuggested fixes:")
        for fix in fixes:
            print(fix.strip())

if __name__ == "__main__":
    main()