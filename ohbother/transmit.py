"""
Packet transmission functionality for OhBother.

This module provides functions and classes for sending packets, either as
individual packets, batches, or continuous streams.
"""

from typing import List, Optional, Union, Dict, Any, Tuple, Callable
import time
from dataclasses import dataclass
import os
import sys
import multiprocessing

from .generated.ohbother import (
    SendPacket as go_send_packet,
    SendPackets as go_send_packets,
    MultiStreamSender as GoMultiStreamSender,
    PacketSequenceSender as GoPacketSequenceSender,
    NewMultiStreamSender,
    NewPacketSequenceSender,
    PacketSendResult as GoPacketSendResult  # Add this import
)

from .generated.go import (
    Slice_byte, 
    nil,
    HardwareAddr
)


from .config import Config, MultiStreamConfig
from .utilities import pass_bytes_to_go


@dataclass
class PacketSendResult:
    """Result of a packet send operation"""
    
    index: int
    """Index of the packet in the original batch"""
    
    total_count: int
    """Total number of packets in the batch"""
    
    elapsed: float
    """Time elapsed since sending started (seconds)"""
    
    error: Optional[str] = None
    """Error message if sending failed"""
    
    @classmethod
    def from_go_result(cls, result: GoPacketSendResult) -> "PacketSendResult":
        """Convert from Go PacketSendResult to Python PacketSendResult"""
        error_str = result.GetError() if result.GetError() else None
        return cls(
            index=result.Index,
            total_count=result.TotalCount,
            elapsed=result.Elapsed,
            error=error_str
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
    """
    if not payloads:
        raise ValueError("Payloads list cannot be empty")
    
    # Just pass the Python list directly
    results = go_send_packets(
        config._get_go_object(),
        payloads,  # Python list
        timeout_ms
    )
    
    # Convert results to Python
    return [PacketSendResult.from_go_result(result) for result in results]


class MultiStreamSender:
    """Handles sending packets across multiple parallel streams."""
    
    def __init__(
        self, 
        config: Config,
        stream_config: Optional[MultiStreamConfig] = None
    ):
        """Initialize multi-stream sender."""
        self._config = config
        self._stream_config = stream_config or MultiStreamConfig()
        
        # Create Go MultiStreamSender with correct rate limit
        self._sender = NewMultiStreamSender(
            config._get_go_object(),
            self._stream_config.rate_limit if hasattr(self._stream_config, 'rate_limit') else 0
        )
        
        # Apply stream configuration with correct property names
        self._sender.SetStreamConfig(
            self._stream_config.packet_workers,
            self._stream_config.stream_count,
            self._stream_config.channel_buffer_size,
            self._stream_config.report_interval
        )
        
        # Apply advanced configuration with correct property names
        self._sender.SetAdvancedConfig(
            self._stream_config.enable_cpu_pinning,
            self._stream_config.disable_ordering,
            self._stream_config.turnstile_burst,
            True  # Always enable metrics
        )
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.flush()
    
    def convert_payloads(self, payloads: List[bytes]) -> List[Slice_byte]:
        """Convert payloads to Go byte slices efficiently using multiprocessing"""
        if not payloads:
            return []
        
        print(f"Converting {len(payloads):,} payloads efficiently...", file=sys.stderr, flush=True)
        
        # Use multiprocessing like in _data.py
        num_workers = max(1, os.cpu_count() - 1)  # Leave one CPU for OS
        
        # Convert function that runs in each worker
        def convert_chunk(data_chunk):
            start_time = time.perf_counter()
            result = [pass_bytes_to_go(p) for p in data_chunk]
            duration = time.perf_counter() - start_time
            print(f"Converted {len(data_chunk):,} payloads in {duration:.3f}s ({len(data_chunk)/duration:,.0f}/s)",
                  file=sys.stderr, flush=True)
            return result
        
        # Split data into chunks - optimal chunk size for conversion
        chunk_size = min(1_000_000, (len(payloads) + num_workers - 1) // num_workers)  # Max 1M items per chunk
        chunks = []
        
        for i in range(0, len(payloads), chunk_size):
            chunks.append(payloads[i:min(i+chunk_size, len(payloads))])
        
        # Process in parallel
        start_time = time.perf_counter()
        with multiprocessing.Pool(processes=num_workers) as pool:
            results = pool.map(convert_chunk, chunks)
        
        # Combine results
        converted = []
        for chunk in results:
            converted.extend(chunk)
        
        total_duration = time.perf_counter() - start_time
        print(f"Total conversion: {len(payloads):,} payloads in {total_duration:.3f}s "
              f"({len(payloads)/total_duration:,.0f}/s)", file=sys.stderr, flush=True)
        
        return converted
    
    def fast_convert_payloads(self, payloads: List[bytes]) -> List[Slice_byte]:
        """Convert payloads in parallel using optimized Go implementation"""
        if not payloads:
            return []
        
        # Import only when needed to avoid circular imports
        from .parallel_utils import parallel_bytes_to_go
        
        # Determine optimal worker count
        num_workers = os.cpu_count() * 2  # Use 2x CPU count for better throughput
        
        print(f"Fast converting {len(payloads):,} payloads with {num_workers} workers...", 
              file=sys.stderr, flush=True)
        
        start_time = time.perf_counter()
        result = parallel_bytes_to_go(payloads, num_workers=num_workers)
        duration = time.perf_counter() - start_time
        
        print(f"Fast conversion complete: {len(payloads):,} payloads in {duration:.3f}s "
              f"({len(payloads)/duration:,.0f}/s)", file=sys.stderr, flush=True)
        
        return result

    def add_batch_payloads(self, payloads: List[bytes], convert: bool = True) -> int:
        """Add multiple payloads in one batch with optional conversion"""
        if not payloads:
            return 0
        
        start_time = time.perf_counter()
        
        # Convert if needed
        if convert:
            converted = self.fast_convert_payloads(payloads)
        else:
            # Assume already converted
            converted = payloads
        
        # Add in batches to avoid potential GIL issues
        batch_size = 100_000  # Add 100k at a time
        added_count = 0
        
        for i in range(0, len(converted), batch_size):
            batch = converted[i:i+batch_size]
            for payload in batch:
                self._sender.AddPayload(payload)
            added_count += len(batch)
        
        duration = time.perf_counter() - start_time
        print(f"Added {added_count:,} payloads in {duration:.3f}s "
              f"({added_count/duration:,.0f}/s)", file=sys.stderr, flush=True)
        
        return added_count

    def add_payloads(self, payloads):
        """Add multiple payloads to the sender.
        
        Args:
            payloads: List of Slice_byte objects to add
        
        Returns:
            Number of payloads added
        """
        if not payloads:
            return 0
        
        # Check the type of the first item to determine handling
        if hasattr(payloads[0], 'handle'):
            # These are Slice_byte objects - add them directly
            for p in payloads:
                self._sender.AddPayload(p)
        else:
            # These might be raw bytes - convert first
            for p in payloads:
                if isinstance(p, bytes):
                    # Convert bytes to Slice_byte
                    slice_obj = Slice_byte.from_bytes(p)
                    self._sender.AddPayload(slice_obj)
                else:
                    # Unknown type - try direct add as last resort
                    self._sender.AddPayload(p)
        
        return len(payloads)

    def send(self):
        """Send all added payloads."""
        error = self._sender.Send()
        if error:
            raise RuntimeError(f"Error sending payloads: {error}")
    
    def flush(self, timeout_ms: int = 1000) -> bool:
        """Flush all pending packets and wait for completion."""
        # Send() initiates the transmission
            
        # Wait for completion
        self._sender.Wait()
        return True
    
    @property
    def metrics(self) -> Dict[str, Any]:
        """Get performance metrics for this sender."""
        go_metrics = self._sender.GetMetrics()
        
        if not go_metrics:
            return {
                "packets_sent": 0,
                "bytes_sent": 0,
                "errors": 0,
                "average_latency_ns": 0,
                "active_workers": 0
            }
            
        # Map Go metrics to Python metrics using safe_get.
        total_packets = safe_get(go_metrics, "packets_processed", 0)
        # Use packet_size from the config if available.
        packet_size = getattr(self._stream_config, "packet_size", 0)
        bytes_sent = total_packets * packet_size
        
        return {
            "packets_sent": total_packets,
            "bytes_sent": bytes_sent,
            "errors": safe_get(go_metrics, "packets_dropped", 0),
            "average_latency_ns": safe_get(go_metrics, "avg_send_ns", 0),
            "prepare_time_ns": safe_get(go_metrics, "prepare_time_ns", 0),
            "wait_time_ns": safe_get(go_metrics, "wait_time_ns", 0),
            "send_time_ns": safe_get(go_metrics, "send_time_ns", 0),
            "avg_prepare_ns": safe_get(go_metrics, "avg_prepare_ns", 0),
            "avg_wait_ns": safe_get(go_metrics, "avg_wait_ns", 0),
            "active_workers": self._stream_config.packet_workers
        }
    
    @property
    def is_complete(self) -> bool:
        """Check if all packets have been sent."""
        return self._sender.IsComplete()
    
    @property
    def sent_count(self) -> int:
        """Get the number of packets sent so far."""
        return self._sender.GetSentCount()
    
    @property 
    def error_count(self) -> int:
        """Get the number of packets that encountered errors."""
        return self._sender.GetErrorCount()
    
    @property
    def is_ordering_enabled(self) -> bool:
        """Check if packet ordering is enabled."""
        return self._sender.IsOrderingEnabled()
    
    @property
    def is_cpu_pinning_enabled(self) -> bool:
        """Check if CPU pinning is enabled."""
        return self._sender.IsCPUPinningEnabled()
    
    @property
    def turnstile_burst(self) -> int:
        """Get the configured burst size."""
        return self._sender.GetTurnstileBurst()
    
    @property
    def are_metrics_enabled(self) -> bool:
        """Check if metrics collection is enabled."""
        return self._sender.AreMetricsEnabled()


class PacketSequenceSender:
    """
    Sends packets in an ordered sequence.
    """
    
    def __init__(
        self,
        config: Config,
        interval_ns: int = 0,
        jitter_ns: int = 0  # Kept for API compatibility
    ):
        """Initialize packet sequence sender."""
        self._config = config
        self._sender = NewPacketSequenceSender(
            config._get_go_object(),
            interval_ns
        )
        self._jitter_ns = jitter_ns
        self._packet_count = 0
    
    def add_packet(self, payload: bytes, sequence_id: int = 0) -> bool:
        """Add a packet to the sequence."""
        if not payload:
            return False
        # Convert Python bytes to Go-compatible format
        payload_go = pass_bytes_to_go(payload)
        self._sender.AddPayload(payload_go)
        self._packet_count += 1
        return True
    
    def add_packets(self, payloads: List[bytes], start_sequence_id: int = 0) -> int:
        """Add multiple packets to the sequence."""
        # No direct AddPackets in Go, so implement with individual calls
        count = 0
        for payload in payloads:
            payload_go = pass_bytes_to_go(payload)
            if payload and self.add_packet(payload_go):
                count += 1
        return count
    
    def send(self, timeout_ms: int = 1000) -> List[PacketSendResult]:
        """Send all packets in the sequence."""
        # Go Send() doesn't take timeout, collects results differently
        self._sender.Send()
        
        # Collect results by repeatedly calling GetNextResult
        results = []
        while not self._sender.IsComplete():
            result = self._sender.GetNextResult()
            if result:
                results.append(PacketSendResult.from_go_result(result))
        
        # One more call to get any final results
        final_result = self._sender.GetNextResult()
        if final_result:
            results.append(PacketSendResult.from_go_result(final_result))
            
        return results
    
    def clear(self) -> None:
        """Clear all packets from the sequence."""
        # No direct Clear() method in Go
        self._sender = NewPacketSequenceSender(
            self._config._get_go_object(),
            self._sender.RateLimit
        )
        self._packet_count = 0
    
    @property
    def count(self) -> int:
        """Number of packets in the sequence."""
        # No direct GetCount() in Go
        return self._packet_count


def safe_get(go_map, key: str, default: int = 0) -> int:
    """
    Retrieve the value for `key` from a Go map that does not implement .get(),
    Returning default if not found.
    """
    try:
        # Try to index directly – if the key does not exist this may raise an error.
        return go_map[key]
    except Exception:
        return default