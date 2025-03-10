"""
Utility functions for OhBother.

This module provides helper functions and utilities for working with the
ohbother library, including platform-specific functions, byte conversions,
and other common operations.
"""

import os
import sys
import socket
import platform
import ipaddress
from typing import List, Dict, Any, Optional, Union, Tuple, Set, Callable
import subprocess
from pathlib import Path

from .generated.go import (
    Slice_byte, 
    nil,
    HardwareAddr
)


# ----- Byte Conversion Utilities -----

def pass_bytes_to_go(data: bytes) -> Slice_byte:
    """
    Convert Python bytes to a Go byte slice.
    
    This is a more descriptive wrapper around the generated Slice_byte.from_bytes method.
    
    Args:
        data: Python bytes object
        
    Returns:
        Slice_byte: Go byte slice
    """
    return Slice_byte.from_bytes(data)


def get_bytes_from_go(go_bytes: Slice_byte) -> bytes:
    """
    Convert a Go byte slice to Python bytes.
    
    Args:
        go_bytes: Go byte slice
        
    Returns:
        bytes: Python bytes object
    """
    return bytes(go_bytes)


def combine_byte_slices(slices: List[Union[bytes, Slice_byte]]) -> bytes:
    """
    Combine multiple byte objects into a single bytes object.
    
    Args:
        slices: List of Python bytes or Go Slice_byte objects
        
    Returns:
        bytes: Combined Python bytes object
    """
    result = bytearray()
    
    for s in slices:
        if isinstance(s, Slice_byte):
            result.extend(bytes(s))
        else:
            result.extend(s)
            
    return bytes(result)


# ----- Hardware Address Utilities -----

def mac_string_to_hardware_addr(mac: str) -> HardwareAddr:
    """
    Convert a MAC address string to a Go HardwareAddr.
    
    Args:
        mac: MAC address string in the format "xx:xx:xx:xx:xx:xx"
        
    Returns:
        HardwareAddr: Go hardware address object
        
    Raises:
        ValueError: If the MAC address is invalid
    """
    if not mac:
        return HardwareAddr()
    
    try:
        # Split and convert hex strings to integers
        mac_bytes = [int(x, 16) for x in mac.split(':')]
        if len(mac_bytes) != 6:
            raise ValueError(f"Invalid MAC address: {mac}")
            
        hw_addr = HardwareAddr()
        for b in mac_bytes:
            hw_addr.append(b)
            
        return hw_addr
    except ValueError:
        raise ValueError(f"Invalid MAC address format: {mac}")


def hardware_addr_to_string(hw_addr: HardwareAddr) -> str:
    """
    Convert a Go HardwareAddr to a MAC address string.
    
    Args:
        hw_addr: Go hardware address object
        
    Returns:
        str: MAC address string in the format "xx:xx:xx:xx:xx:xx"
    """
    if not hw_addr or len(hw_addr) == 0:
        return ""
        
    return ':'.join(f'{b:02x}' for b in hw_addr)


# ----- Network Interface Utilities -----

def get_network_interfaces() -> Dict[str, Dict[str, Any]]:
    """
    Get information about available network interfaces.
    
    Returns:
        Dict mapping interface names to properties including:
            - mac: MAC address
            - ip: List of IP addresses
            - is_up: Whether the interface is up
            - is_loopback: Whether this is a loopback interface
    """
    interfaces = {}
    
    for iface_name in socket.if_nameindex():
        name = iface_name[1]
        info = {}
        
        try:
            # Get interface addresses
            addrs = socket.getaddrinfo(socket.gethostname(), None)
            info['ip'] = [addr[4][0] for addr in addrs 
                          if addr[0] == socket.AF_INET]
            
            # Try to get the MAC address - platform specific
            if sys.platform.startswith('linux'):
                try:
                    with open(f'/sys/class/net/{name}/address', 'r') as f:
                        info['mac'] = f.read().strip()
                except (IOError, FileNotFoundError):
                    info['mac'] = ""
            elif sys.platform == 'darwin':
                # On macOS, we need to run ifconfig
                try:
                    output = subprocess.check_output(['ifconfig', name], 
                                                    universal_newlines=True)
                    for line in output.split('\n'):
                        if 'ether' in line:
                            info['mac'] = line.split('ether')[1].strip().split()[0]
                            break
                except subprocess.SubprocessError:
                    info['mac'] = ""
            else:
                # On Windows, use ipconfig /all
                info['mac'] = ""
            
            # Check if the interface is up and if it's a loopback
            info['is_up'] = True  # We assume it's up if we can get info
            info['is_loopback'] = name.startswith('lo')
            
            interfaces[name] = info
        except (socket.error, ValueError):
            continue
    
    return interfaces


def get_default_interface() -> Optional[str]:
    """
    Get the name of the default network interface.
    
    Returns:
        str: Name of the default interface or None if not found
    """
    interfaces = get_network_interfaces()
    
    # First try to find a non-loopback interface that's up
    for name, info in interfaces.items():
        if info.get('is_up', False) and not info.get('is_loopback', False):
            return name
    
    # If that fails, just return the first one that's up
    for name, info in interfaces.items():
        if info.get('is_up', False):
            return name
    
    return None


# ----- OS and Platform Utilities -----

def get_platform_info() -> Dict[str, str]:
    """
    Get information about the current platform.
    
    Returns:
        Dict with platform information including:
            - os: Operating system name
            - version: OS version
            - architecture: CPU architecture
            - machine: Machine type
            - processor: Processor name
    """
    return {
        'os': platform.system(),
        'version': platform.version(),
        'architecture': platform.architecture()[0],
        'machine': platform.machine(),
        'processor': platform.processor()
    }


def set_process_priority(high_priority: bool = False) -> bool:
    """
    Set the process priority.
    
    Args:
        high_priority: If True, set to high priority, otherwise normal
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        if sys.platform == 'win32':
            import psutil
            p = psutil.Process(os.getpid())
            if high_priority:
                p.nice(psutil.HIGH_PRIORITY_CLASS)
            else:
                p.nice(psutil.NORMAL_PRIORITY_CLASS)
        else:
            import resource
            if high_priority:
                os.nice(-10)  # Higher priority
            else:
                os.nice(0)    # Normal priority
        return True
    except (ImportError, OSError, ValueError):
        return False


def pin_to_cpu(cpu_id: int) -> bool:
    """
    Pin the current process to a specific CPU core.
    
    Args:
        cpu_id: CPU core ID to pin to
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        if sys.platform == 'win32':
            # On Windows
            import psutil
            p = psutil.Process(os.getpid())
            p.cpu_affinity([cpu_id])
        else:
            # On Linux/macOS
            import psutil
            p = psutil.Process(os.getpid())
            p.cpu_affinity([cpu_id])
        return True
    except (ImportError, AttributeError, ValueError, OSError):
        return False


def get_cpu_count() -> int:
    """
    Get the number of CPU cores available.
    
    Returns:
        int: Number of CPU cores
    """
    try:
        import multiprocessing
        return multiprocessing.cpu_count()
    except (ImportError, NotImplementedError):
        return 1


# ----- File and Path Utilities -----

def get_library_path() -> Path:
    """
    Get the path to the library's installed location.
    
    Returns:
        Path: Directory path where the library is installed
    """
    return Path(__file__).parent.absolute()


def get_lib_file_path() -> Optional[Path]:
    """
    Get the path to the native library file (.so/.dll/.dylib).
    
    Returns:
        Path: Path to the native library file or None if not found
    """
    lib_dir = get_library_path() / 'generated'
    
    if sys.platform.startswith('linux'):
        lib_file = lib_dir / '_ohbother.so'
    elif sys.platform == 'darwin':
        lib_file = lib_dir / '_ohbother.dylib'
    elif sys.platform == 'win32':
        lib_file = lib_dir / '_ohbother.dll'
    else:
        return None
        
    if lib_file.exists():
        return lib_file
    
    return None


# ----- Validation Utilities -----

def is_valid_mac_address(mac: str) -> bool:
    """
    Check if a string is a valid MAC address.
    
    Args:
        mac: MAC address string in the format "xx:xx:xx:xx:xx:xx"
        
    Returns:
        bool: True if valid, False otherwise
    """
    if not mac:
        return False
        
    parts = mac.split(':')
    if len(parts) != 6:
        return False
        
    try:
        for part in parts:
            value = int(part, 16)
            if value < 0 or value > 255:
                return False
    except ValueError:
        return False
        
    return True


def is_valid_ip_address(ip: str) -> bool:
    """
    Check if a string is a valid IP address.
    
    Args:
        ip: IP address string
        
    Returns:
        bool: True if valid, False otherwise
    """
    if not ip:
        return False
        
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False


def is_valid_port(port: int) -> bool:
    """
    Check if a number is a valid port number.
    
    Args:
        port: Port number
        
    Returns:
        bool: True if valid, False otherwise
    """
    return isinstance(port, int) and 0 <= port <= 65535


# ----- Format Conversion Utilities -----

def bytes_to_hex(data: bytes, delimiter: str = ' ') -> str:
    """
    Convert bytes to a hexadecimal string.
    
    Args:
        data: Bytes to convert
        delimiter: Delimiter between bytes (default: space)
        
    Returns:
        str: Hexadecimal string
    """
    return delimiter.join(f'{b:02x}' for b in data)


def hex_to_bytes(hex_str: str) -> bytes:
    """
    Convert a hexadecimal string to bytes.
    
    Args:
        hex_str: Hexadecimal string (can contain spaces, colons)
        
    Returns:
        bytes: Converted bytes
    """
    # Remove any non-hex characters
    hex_str = ''.join(c for c in hex_str if c.isalnum())
    
    # Make sure we have an even number of digits
    if len(hex_str) % 2 != 0:
        hex_str = '0' + hex_str
    
    return bytes.fromhex(hex_str)