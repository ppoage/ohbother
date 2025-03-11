"""
Benchmarking utilities for OhBother.

This module provides tools for measuring performance of packet processing
operations, including throughput, latency, and resource utilization.
"""

import time
import statistics
import threading
from typing import List, Dict, Any, Optional, Tuple, Callable, Union
from dataclasses import dataclass

from .config import Config, MultiStreamConfig
from .transmit import MultiStreamSender, send_packets, PacketSendResult
from .receive import receive_packets_by_count, receive_packets_by_time, PacketStats
from .generated.ohbother import (
    BenchmarkSend as go_benchmark_send,
    BenchmarkReceiveAsync as go_benchmark_receive_async
)

@dataclass
class BenchmarkOptions:
    """Configuration options for benchmarks."""
    
    packet_size: int = 1024
    """Size of packets to use in the benchmark (bytes)."""
    
    packet_count: int = 10000
    """Number of packets to send/receive."""
    
    duration: float = 0.0
    """Duration of the benchmark in seconds (0 = use packet_count)."""
    
    parallel_streams: int = 1
    """Number of concurrent streams."""
    
    warmup_packets: int = 100
    """Number of packets to send as warmup."""
    
    cooldown_seconds: float = 0.5
    """Time to wait after benchmark completion."""
    
    report_interval: float = 1.0
    """Interval for progress reporting."""
    
    payload_pattern: bytes = b'\x00'
    """Pattern to use for packet payloads."""
    
    rate_limit: int = 0
    """Rate limit in nanoseconds between packets (0 = unlimited)."""


@dataclass
class BenchmarkResult:
    """Results of a benchmark run."""
    
    packets_sent: int = 0
    """Total number of packets sent."""
    
    packets_received: int = 0
    """Total number of packets received."""
    
    bytes_sent: int = 0
    """Total bytes sent."""
    
    bytes_received: int = 0
    """Total bytes received."""
    
    duration: float = 0.0
    """Actual duration of the benchmark in seconds."""
    
    send_errors: int = 0
    """Number of packet send errors."""
    
    receive_errors: int = 0
    """Number of packet receive errors."""
    
    latency_min_ms: float = 0.0
    """Minimum observed latency in milliseconds."""
    
    latency_max_ms: float = 0.0
    """Maximum observed latency in milliseconds."""
    
    latency_avg_ms: float = 0.0
    """Average observed latency in milliseconds."""
    
    latency_p50_ms: float = 0.0
    """50th percentile (median) latency in milliseconds."""
    
    latency_p95_ms: float = 0.0
    """95th percentile latency in milliseconds."""
    
    latency_p99_ms: float = 0.0
    """99th percentile latency in milliseconds."""
    
    rate: float = 0.0
    """Rate in packets per second (returned by Go)"""
    
    @property
    def packets_per_second(self) -> float:
        """Calculate packets sent per second."""
        return self.rate
    
    @property
    def receive_rate(self) -> float:
        """Calculate packets received per second."""
        if self.duration <= 0:
            return 0
        return self.packets_received / self.duration
    
    @property
    def send_throughput_mbps(self) -> float:
        """Calculate send throughput in megabits per second."""
        if self.duration <= 0:
            return 0
        return (self.bytes_sent * 8) / (self.duration * 1_000_000)
    
    @property
    def receive_throughput_mbps(self) -> float:
        """Calculate receive throughput in megabits per second."""
        if self.duration <= 0:
            return 0
        return (self.bytes_received * 8) / (self.duration * 1_000_000)
    
    @property
    def packet_loss_rate(self) -> float:
        """Calculate packet loss rate as a percentage."""
        if self.packets_sent <= 0:
            return 0
        return 100.0 * (self.packets_sent - self.packets_received) / self.packets_sent
    
    def __str__(self) -> str:
        """Format benchmark results as a readable string."""
        return (
            f"Benchmark Results:\n"
            f"  Duration: {self.duration:.3f}s\n"
            f"  Packets: {self.packets_sent:,} sent, {self.packets_received:,} received "
            f"({self.packet_loss_rate:.2f}% loss)\n"
            f"  Throughput: {self.send_throughput_mbps:.2f} Mbps sent, "
            f"{self.receive_throughput_mbps:.2f} Mbps received\n"
            f"  Packet Rate: {self.packets_per_second:.2f} pps sent, "
            f"{self.receive_rate:.2f} pps received\n"
            f"  Latency: {self.latency_avg_ms:.3f}ms avg, "
            f"{self.latency_min_ms:.3f}ms min, {self.latency_max_ms:.3f}ms max\n"
            f"  Latency Percentiles: p50={self.latency_p50_ms:.3f}ms, "
            f"p95={self.latency_p95_ms:.3f}ms, p99={self.latency_p99_ms:.3f}ms\n"
            f"  Errors: {self.send_errors} send, {self.receive_errors} receive"
        )


def run_benchmark(
    config: Config,
    options: Optional[BenchmarkOptions] = None,
    progress_callback: Optional[Callable[[float, BenchmarkResult], None]] = None
) -> BenchmarkResult:
    """
    Run a benchmark using the given configuration.
    
    Uses the native Go benchmark functions for optimal performance.
    
    Args:
        config: Packet processing configuration
        options: Benchmark configuration options
        progress_callback: Optional callback to report progress
            Called with (progress_pct, partial_results)
    
    Returns:
        BenchmarkResult: Results of the benchmark
    """
    # Use default options if none provided
    if options is None:
        options = BenchmarkOptions()
    
    # Initialize results
    result = BenchmarkResult()
    
    # Set up the receiver if we need to measure received packets
    receiver = None
    if config.pcap.interface.startswith("lo"):  # Loopback mode
        try:
            # Start async receiver if we're using loopback
            if options.duration > 0:
                receiver_duration = options.duration + 2.0  # Add buffer time
                receiver = go_benchmark_receive_async(config._get_go_object(), receiver_duration)
            else:
                # For packet count mode, estimate duration
                est_duration = (options.packet_count / 5000) * 5.0  # Estimate 5000 packets/sec
                receiver_duration = max(5.0, est_duration * 2.0)  # Min 5 seconds with 2x buffer
                receiver = go_benchmark_receive_async(config._get_go_object(), receiver_duration)
        except Exception as e:
            print(f"Warning: Could not set up receiver: {e}")
    
    # Allow time for receiver to start capturing
    if receiver:
        time.sleep(0.2)
    
    # Report initial progress
    if progress_callback:
        progress_callback(0.0, result)
    
    # Start timing
    start_time = time.time()
    
    try:
        # Call Go benchmark function - this blocks until completion
        if options.duration > 0:
            # Convert duration to packet count
            # Estimate based on 10,000 packets/sec rate
            packet_count = int(options.duration * 10000)
        else:
            packet_count = options.packet_count
        
        # Call the Go benchmark function which returns packets/sec rate
        rate = go_benchmark_send(
            config._get_go_object(),
            packet_count,
            options.packet_size, 
            options.rate_limit
        )
        
        # Update results
        end_time = time.time()
        result.duration = end_time - start_time
        result.packets_sent = packet_count
        result.bytes_sent = packet_count * options.packet_size
        result.rate = rate  # Store the rate returned by Go
        
        # Set 100% progress at the end
        if progress_callback:
            progress_callback(100.0, result)
        
        # Get receiver results if available
        if receiver:
            try:
                # Wait for cooldown to ensure all packets are captured
                time.sleep(options.cooldown_seconds)
                
                # Get received packets
                received_packets = receiver.ResultNative()
                result.packets_received = len(received_packets)
                result.bytes_received = sum(len(p) for p in received_packets)
            except Exception as e:
                print(f"Error collecting receiver results: {e}")
    
    except Exception as e:
        print(f"Benchmark error: {e}")
    
    # Wait for cooldown
    time.sleep(options.cooldown_seconds)
    
    return result


class PerfTest:
    """
    Performance testing framework for ohbother.
    
    Provides methods for running various performance tests and collecting
    results for analysis.
    """
    
    def __init__(self, config: Config):
        """
        Initialize performance tester.
        
        Args:
            config: Base configuration for tests
        """
        self.config = config
        self.results = {}
    
    def throughput_test(
        self,
        packet_sizes: List[int] = None,
        duration: float = 5.0,
        parallel_streams: int = 1
    ) -> Dict[int, BenchmarkResult]:
        """
        Test maximum throughput with different packet sizes.
        
        Args:
            packet_sizes: List of packet sizes to test in bytes
            duration: Duration for each test in seconds
            parallel_streams: Number of parallel streams to use
            
        Returns:
            Dict mapping packet sizes to benchmark results
        """
        if packet_sizes is None:
            packet_sizes = [64, 512, 1024, 4096, 9000]
        
        results = {}
        for size in packet_sizes:
            print(f"Testing packet size: {size} bytes")
            options = BenchmarkOptions(
                packet_size=size,
                duration=duration,
                parallel_streams=parallel_streams
            )
            
            result = run_benchmark(
                self.config, 
                options,
                lambda p, r: print(f"Progress: {p:.1f}%, " 
                                   f"Rate: {r.packets_per_second:.2f} pps, "
                                   f"Throughput: {r.send_throughput_mbps:.2f} Mbps")
            )
            
            results[size] = result
            print(f"Completed {size} bytes test: {result.send_throughput_mbps:.2f} Mbps")
            print()
        
        self.results["throughput"] = results
        return results
    
    def latency_test(
        self,
        packet_count: int = 1000,
        packet_size: int = 512
    ) -> BenchmarkResult:
        """
        Test packet processing latency.
        
        Args:
            packet_count: Number of packets to test
            packet_size: Size of packets in bytes
            
        Returns:
            BenchmarkResult with latency measurements
        """
        print(f"Running latency test with {packet_count} packets of {packet_size} bytes")
        
        # Use a single stream for latency testing
        options = BenchmarkOptions(
            packet_size=packet_size,
            packet_count=packet_count,
            parallel_streams=1,
            report_interval=0.5
        )
        
        result = run_benchmark(
            self.config,
            options,
            lambda p, r: print(f"Progress: {p:.1f}%, "
                              f"Avg latency: {r.latency_avg_ms:.3f} ms")
        )
        
        print(f"Latency test completed:")
        print(f"  Average: {result.latency_avg_ms:.3f} ms")
        print(f"  Minimum: {result.latency_min_ms:.3f} ms")
        print(f"  Maximum: {result.latency_max_ms:.3f} ms")
        print(f"  Median (p50): {result.latency_p50_ms:.3f} ms")
        print(f"  p95: {result.latency_p95_ms:.3f} ms")
        print(f"  p99: {result.latency_p99_ms:.3f} ms")
        
        self.results["latency"] = result
        return result
    
    def scalability_test(
        self,
        max_streams: int = 8,
        packet_size: int = 1024,
        duration: float = 3.0
    ) -> Dict[int, BenchmarkResult]:
        """
        Test how performance scales with number of parallel streams.
        
        Args:
            max_streams: Maximum number of parallel streams to test
            packet_size: Size of packets in bytes
            duration: Duration for each test in seconds
            
        Returns:
            Dict mapping stream counts to benchmark results
        """
        results = {}
        stream_counts = [1]
        streams = 2
        
        while streams <= max_streams:
            stream_counts.append(streams)
            streams *= 2
        
        for streams in stream_counts:
            print(f"Testing with {streams} parallel streams")
            options = BenchmarkOptions(
                packet_size=packet_size,
                duration=duration,
                parallel_streams=streams
            )
            
            result = run_benchmark(
                self.config,
                options,
                lambda p, r: print(f"Progress: {p:.1f}%, "
                                  f"Throughput: {r.send_throughput_mbps:.2f} Mbps")
            )
            
            results[streams] = result
            print(f"Completed {streams} streams test: {result.send_throughput_mbps:.2f} Mbps")
            print()
        
        self.results["scalability"] = results
        return results