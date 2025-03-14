"""
Packet reception functionality for OhBother.

This module provides classes and functions for receiving network packets,
either for a fixed duration, a specified packet count, or as a continuous stream.
"""

from typing import List, Optional, Union, Tuple, Iterator
import time
import threading
from dataclasses import dataclass

from .generated.go import (
    receive_PacketReceiver as GoPacketReceiver,
    receive_AsyncResult as AsyncResult,
    #receive_ContinuousPacketReceiver as GoContinuousPacketReceiver
    

)

# from .generated.ohbother import (
#     #PacketReceiver as GoPacketReceiver,
#     #ContinuousPacketReceiver as GoContinuousPacketReceiver
# )
from .config import Config
from .receive import (
    #GoPacketReceiver, ContinuousPacketReceiver,
    PacketReceiverByTime as go_packet_receiver_by_time,
    PacketReceiverByCount, ReceivePacketsByTimeSync, 
    ReceivePacketsByCountSync
)

#from .receive import NewReceiver as new_go_receiver

def receive_packets_by_time(
    config: Config,
    duration: float,
    wait: bool = True
) -> Union[List[bytes], GoPacketReceiver]:
    """
    Receive packets for a specified duration.
    
    Args:
        config: The configuration for packet reception
        duration: Time in seconds to receive packets
        wait: Whether to wait for completion and return packets (True)
              or return the receiver immediately (False)
              
    Returns:
        If wait=True: List of received packet payloads as bytes objects
        If wait=False: A PacketReceiver that can be used to get results later
    """
    receiver = go_packet_receiver_by_time(config._get_go_object(), duration)
    
    if wait:
        # Wait for completion and return the packets
        return receiver.ResultNative()
    
    # Return the receiver for later use
    return receiver


def receive_packets_by_count(
    config: Config,
    count: int,
    timeout: float = 0.0,
    wait: bool = True
) -> Union[List[bytes], GoPacketReceiver]:
    """
    Receive a specified number of packets, optionally with a timeout.
    
    Args:
        config: The configuration for packet reception
        count: Number of packets to receive
        timeout: Maximum time in seconds to wait (0 = no timeout)
        wait: Whether to wait for completion and return packets (True)
              or return the receiver immediately (False)
              
    Returns:
        If wait=True: List of received packet payloads as bytes objects
        If wait=False: A PacketReceiver that can be used to get results later
    """
    receiver = go_packet_receiver_by_count(config._get_go_object(), count, timeout)
    
    if wait:
        # Wait for completion and return the packets
        return receiver.ResultNative()
    
    # Return the receiver for later use
    return receiver


class ContinuousPacketReceiver:
    """
    A continuous packet receiver that provides a streaming interface.
    
    This class provides a way to receive packets continuously in a streaming
    fashion, rather than waiting for a batch of packets to complete.
    """
    
    def __init__(self, config: Config):
        """
        Initialize a continuous packet receiver.
        
        Args:
            config: The configuration for packet reception
        """
        self._receiver = new_go_receiver(config._get_go_object())
        self._closed = False
    
    def get_next_packet(self) -> Optional[bytes]:
        """
        Get the next available packet.
        
        Returns:
            The next packet payload as bytes, or None if no packet is available
            or the receiver has been closed.
        """
        if self._closed:
            return None
            
        return self._receiver.GetNextPacket()
    
    def close(self) -> None:
        """Close the receiver and release resources."""
        if not self._closed:
            self._receiver.Close()
            self._closed = True
    
    def __enter__(self) -> 'ContinuousPacketReceiver':
        """Enable use with 'with' statement."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Close the receiver when exiting the 'with' block."""
        self.close()
    
    def __iter__(self) -> Iterator[bytes]:
        """
        Allow iterating over received packets.
        
        Example:
            with ContinuousPacketReceiver(config) as receiver:
                for packet in receiver:
                    process_packet(packet)
        """
        return self
    
    def __next__(self) -> bytes:
        """Get the next packet when iterating."""
        packet = self.get_next_packet()
        if packet is None:
            raise StopIteration
        return packet


@dataclass
class PacketStats:
    """Statistics about received packets."""
    
    count: int = 0
    """Total number of packets received."""
    
    bytes_received: int = 0
    """Total number of bytes received."""
    
    start_time: float = 0.0
    """Time when reception started (seconds since epoch)."""
    
    end_time: float = 0.0
    """Time when reception ended (seconds since epoch)."""
    
    @property
    def duration(self) -> float:
        """Duration of packet reception in seconds."""
        if self.start_time == 0:
            return 0.0
        end = self.end_time if self.end_time > 0 else time.time()
        return end - self.start_time
    
    @property
    def packets_per_second(self) -> float:
        """Average packet rate in packets per second."""
        dur = self.duration
        if dur == 0:
            return 0.0
        return self.count / dur
    
    @property
    def bytes_per_second(self) -> float:
        """Average throughput in bytes per second."""
        dur = self.duration
        if dur == 0:
            return 0.0
        return self.bytes_received / dur


def receive_with_stats(
    config: Config,
    duration: float = 0.0,
    count: int = 0,
    callback: Optional[callable] = None
) -> Tuple[List[bytes], PacketStats]:
    """
    Receive packets and collect statistics.
    
    Args:
        config: The configuration for packet reception
        duration: Time in seconds to receive packets (if count=0)
        count: Number of packets to receive (if duration=0)
        callback: Optional function to call for each packet
                  with signature: callback(packet: bytes, stats: PacketStats)
    
    Returns:
        Tuple of (packets, stats) where:
          - packets is a list of received packet payloads
          - stats is a PacketStats object with reception statistics
    
    Note: 
        Either duration or count must be specified. If both are specified,
        reception will stop when either condition is met.
    """
    if duration <= 0 and count <= 0:
        raise ValueError("Either duration or count must be positive")
    
    stats = PacketStats()
    stats.start_time = time.time()
    packets = []
    
    # Use the appropriate method depending on what was specified
    if count > 0 and duration > 0:
        # Both specified - use count with timeout
        receiver = go_packet_receiver_by_count(config._get_go_object(), count, duration)
        result_packets = receiver.ResultNative()
    elif count > 0:
        # Only count specified
        receiver = go_packet_receiver_by_count(config._get_go_object(), count, 0)
        result_packets = receiver.ResultNative()
    else:
        # Only duration specified
        receiver = go_packet_receiver_by_time(config._get_go_object(), duration)
        result_packets = receiver.ResultNative()
    
    # Process the packets
    for pkt in result_packets:
        packets.append(pkt)
        stats.count += 1
        stats.bytes_received += len(pkt)
        
        # Call the callback if provided
        if callback:
            callback(pkt, stats)
    
    # Finalize the stats
    stats.end_time = time.time()
    
    return packets, stats