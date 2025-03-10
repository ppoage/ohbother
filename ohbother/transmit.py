"""
Packet transmission functionality for OhBother.

This module provides functions and classes for sending packets, either as
individual packets, batches, or continuous streams.
"""

from typing import List, Optional, Union, Dict, Any, Tuple, Callable
import time
from dataclasses import dataclass

from .generated.ohbother import (
    Transmitter,
    SendPacket as go_send_packet,
    SendPackets as go_send_packets,
    PacketBatch,
    MultiStreamSender as GoMultiStreamSender,
    PacketSequenceSender as GoPacketSequenceSender,
    SendResult,
    NewTransmitter,
    NewMultiStreamSender,
    NewPacketSequenceSender
)
from .config import Config, MultiStreamConfig


@dataclass
class PacketSendResult:
    """Result of a packet send operation"""
    
    success: bool
    """Whether the packet was sent successfully"""
    
    bytes_sent: int
    """Number of bytes sent"""
    
    timestamp: float
    """Timestamp when the packet was sent (seconds since epoch)"""
    
    error_message: str = ""
    """Error message if the send failed"""
    
    @classmethod
    def from_go_result(cls, result: SendResult) -> "PacketSendResult":
        """Convert from Go SendResult to Python PacketSendResult"""
        return cls(
            success=result.Success,
            bytes_sent=result.BytesSent,
            timestamp=result.Timestamp,
            error_message=result.ErrorMessage
        )


def send_packet(
    config: Config, 
    payload: bytes,
    timeout_ms: int = 100
) -> PacketSendResult:
    """
    Send a single packet.
    
    Args:
        config: Packet configuration
        payload: Raw packet payload bytes
        timeout_ms: Send timeout in milliseconds
    
    Returns:
        PacketSendResult: Result of the send operation
    
    Raises:
        ValueError: If payload is empty
        RuntimeError: If packet sending fails
    """
    if not payload:
        raise ValueError("Payload cannot be empty")
    
    result = go_send_packet(
        config._get_go_object(),
        payload,
        timeout_ms
    )
    
    return PacketSendResult.from_go_result(result)


def send_packets(
    config: Config,
    payloads: List[bytes],
    timeout_ms: int = 100
) -> List[PacketSendResult]:
    """
    Send multiple packets.
    
    Args:
        config: Packet configuration
        payloads: List of raw packet payload bytes
        timeout_ms: Send timeout in milliseconds
    
    Returns:
        List[PacketSendResult]: Results for each packet send operation
    
    Raises:
        ValueError: If payloads list is empty
        RuntimeError: If packet sending fails
    """
    if not payloads:
        raise ValueError("Payloads list cannot be empty")
    
    # Create a Go PacketBatch from the Python list
    batch = PacketBatch()
    for payload in payloads:
        if payload:  # Skip empty payloads
            batch.append(payload)
    
    # Send the batch
    results = go_send_packets(
        config._get_go_object(),
        batch,
        timeout_ms
    )
    
    # Convert results to Python
    return [PacketSendResult.from_go_result(result) for result in results]


class Transmitter:
    """Handles packet transmission with configurable parameters."""
    
    def __init__(self, config: Config):
        """
        Initialize transmitter with configuration.
        
        Args:
            config: Packet transmission configuration
        """
        self._config = config
        self._transmitter = NewTransmitter(config._get_go_object())
    
    def send(self, payload: bytes, timeout_ms: int = 100) -> PacketSendResult:
        """
        Send a single packet.
        
        Args:
            payload: Raw packet payload bytes
            timeout_ms: Send timeout in milliseconds
            
        Returns:
            PacketSendResult: Result of the send operation
        """
        result = self._transmitter.Send(payload, timeout_ms)
        return PacketSendResult.from_go_result(result)
    
    def send_batch(self, payloads: List[bytes], timeout_ms: int = 100) -> List[PacketSendResult]:
        """
        Send a batch of packets.
        
        Args:
            payloads: List of raw packet payload bytes
            timeout_ms: Send timeout in milliseconds
            
        Returns:
            List[PacketSendResult]: Results for each packet send operation
        """
        # Create a Go PacketBatch
        batch = PacketBatch()
        for payload in payloads:
            if payload:  # Skip empty payloads
                batch.append(payload)
                
        results = self._transmitter.SendBatch(batch, timeout_ms)
        return [PacketSendResult.from_go_result(result) for result in results]
    
    def close(self) -> None:
        """Close transmitter and release resources."""
        self._transmitter.Close()


class MultiStreamSender:
    """
    Handles sending packets across multiple parallel streams.
    
    This class optimizes packet transmission by using multiple sender threads
    and can be configured for different performance characteristics.
    """
    
    def __init__(
        self, 
        config: Config,
        stream_config: Optional[MultiStreamConfig] = None
    ):
        """
        Initialize multi-stream sender.
        
        Args:
            config: Base packet configuration
            stream_config: Multi-stream specific configuration
        """
        self._config = config
        self._stream_config = stream_config or MultiStreamConfig()
        
        # Create the Go MultiStreamSender
        self._sender = NewMultiStreamSender(
            config._get_go_object(),
            self._stream_config._get_go_object()
        )
    
    def start(self) -> None:
        """
        Start the sender workers.
        
        This must be called before sending any packets.
        """
        self._sender.Start()
    
    def send(self, payload: bytes, stream_id: int = 0) -> bool:
        """
        Send a packet on a specific stream.
        
        Args:
            payload: Raw packet payload bytes
            stream_id: Stream identifier (must be less than stream_count)
            
        Returns:
            bool: True if packet was queued successfully
            
        Raises:
            ValueError: If stream_id is invalid
            RuntimeError: If sender is not started
        """
        if stream_id < 0 or stream_id >= self._stream_config.stream_count:
            raise ValueError(f"Stream ID must be between 0 and {self._stream_config.stream_count-1}")
            
        return self._sender.Send(payload, stream_id)
    
    def send_batch(self, payloads: List[bytes], stream_id: int = 0) -> int:
        """
        Send a batch of packets on a specific stream.
        
        Args:
            payloads: List of raw packet payload bytes
            stream_id: Stream identifier (must be less than stream_count)
            
        Returns:
            int: Number of packets successfully queued
            
        Raises:
            ValueError: If stream_id is invalid
            RuntimeError: If sender is not started
        """
        if stream_id < 0 or stream_id >= self._stream_config.stream_count:
            raise ValueError(f"Stream ID must be between 0 and {self._stream_config.stream_count-1}")
            
        # Create a Go PacketBatch
        batch = PacketBatch()
        for payload in payloads:
            if payload:  # Skip empty payloads
                batch.append(payload)
                
        return self._sender.SendBatch(batch, stream_id)
    
    def flush(self, timeout_ms: int = 1000) -> bool:
        """
        Flush all pending packets and wait for completion.
        
        Args:
            timeout_ms: Maximum time to wait for flush to complete
            
        Returns:
            bool: True if all packets were sent successfully
        """
        return self._sender.Flush(timeout_ms)
    
    def stop(self) -> None:
        """
        Stop the sender workers and release resources.
        
        This should be called when done with the sender.
        """
        self._sender.Stop()
    
    @property
    def metrics(self) -> Dict[str, Any]:
        """Get performance metrics for this sender."""
        go_metrics = self._sender.GetMetrics()
        
        return {
            "packets_sent": go_metrics.PacketsSent,
            "bytes_sent": go_metrics.BytesSent,
            "errors": go_metrics.Errors,
            "average_latency_ns": go_metrics.AvgLatencyNs,
            "active_workers": go_metrics.ActiveWorkers
        }
    
    def __enter__(self) -> "MultiStreamSender":
        """Context manager entry."""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.flush()
        self.stop()


class PacketSequenceSender:
    """
    Sends packets in an ordered sequence.
    
    This class ensures packets are sent in the correct order with configurable
    timing between each packet.
    """
    
    def __init__(
        self,
        config: Config,
        interval_ns: int = 0,
        jitter_ns: int = 0
    ):
        """
        Initialize packet sequence sender.
        
        Args:
            config: Packet configuration
            interval_ns: Nanoseconds between packet transmissions (0 = as fast as possible)
            jitter_ns: Random jitter to add to intervals (0 = constant interval)
        """
        self._config = config
        self._sender = NewPacketSequenceSender(
            config._get_go_object(),
            interval_ns,
            jitter_ns
        )
    
    def add_packet(self, payload: bytes, sequence_id: int = 0) -> bool:
        """
        Add a packet to the sequence.
        
        Args:
            payload: Raw packet payload bytes
            sequence_id: Position in sequence (0 = next available)
            
        Returns:
            bool: True if packet was added successfully
        """
        return self._sender.AddPacket(payload, sequence_id)
    
    def add_packets(self, payloads: List[bytes], start_sequence_id: int = 0) -> int:
        """
        Add multiple packets to the sequence.
        
        Args:
            payloads: List of raw packet payload bytes
            start_sequence_id: Starting sequence ID (0 = next available)
            
        Returns:
            int: Number of packets added successfully
        """
        # Create a Go PacketBatch
        batch = PacketBatch()
        for payload in payloads:
            if payload:  # Skip empty payloads
                batch.append(payload)
                
        return self._sender.AddPackets(batch, start_sequence_id)
    
    def send(self, timeout_ms: int = 1000) -> List[PacketSendResult]:
        """
        Send all packets in the sequence.
        
        Args:
            timeout_ms: Maximum time to wait for completion
            
        Returns:
            List[PacketSendResult]: Results for each packet send operation
        """
        results = self._sender.Send(timeout_ms)
        return [PacketSendResult.from_go_result(result) for result in results]
    
    def clear(self) -> None:
        """Clear all packets from the sequence."""
        self._sender.Clear()
    
    @property
    def count(self) -> int:
        """Number of packets in the sequence."""
        return self._sender.GetCount()