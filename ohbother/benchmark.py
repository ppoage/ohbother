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
    BenchmarkSender as GoBenchmarkSender,
    BenchmarkReceiver as GoBenchmarkReceiver,
    BenchmarkResult,
    RunBenchmark as go_run_benchmark,
    NewBenchmarkSender,
    NewBenchmarkReceiver
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
    
    @property
    def packets_per_second(self) -> float:
        """Calculate packets sent per second."""
        if self.duration <= 0:
            return 0
        return self.packets_sent / self.duration
    
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
    
    # Create the benchmark objects
    stream_config = MultiStreamConfig(packet_workers=options.parallel_streams)
    
    # Generate a payload
    payload = options.payload_pattern * (options.packet_size // len(options.payload_pattern))
    payload = payload[:options.packet_size]  # Ensure exact size
    
    # Initialize results
    result = BenchmarkResult()
    latencies = []
    
    # Setup sender and receiver
    sender = MultiStreamSender(config, stream_config)
    sender.start()
    
    # Determine benchmark duration and packet count
    if options.duration > 0:
        end_time = time.time() + options.duration
        target_packets = None
    else:
        end_time = None
        target_packets = options.packet_count
    
    # Warmup phase
    if options.warmup_packets > 0:
        warmup_payloads = [payload] * options.warmup_packets
        sender.send_batch(warmup_payloads)
        time.sleep(0.1)  # Brief pause after warmup
    
    # Start timing
    start_time = time.time()
    last_progress_time = start_time
    
    try:
        # Main benchmark loop
        packet_count = 0
        while True:
            # Check if we're done
            if end_time and time.time() >= end_time:
                break
            if target_packets and packet_count >= target_packets:
                break
            
            # Send a packet
            send_time = time.time()
            success = sender.send(payload, packet_count % options.parallel_streams)
            
            if success:
                packet_count += 1
                result.packets_sent += 1
                result.bytes_sent += len(payload)
                
                # Track latency if this is a loopback test
                if config.pcap.interface.startswith("lo"):
                    latency_ms = (time.time() - send_time) * 1000
                    latencies.append(latency_ms)
            else:
                result.send_errors += 1
            
            # Report progress periodically
            current_time = time.time()
            if (progress_callback and 
                    current_time - last_progress_time >= options.report_interval):
                last_progress_time = current_time
                progress = 0.0
                
                if target_packets:
                    progress = min(100.0, 100.0 * packet_count / target_packets)
                elif end_time:
                    elapsed = current_time - start_time
                    total = end_time - start_time
                    progress = min(100.0, 100.0 * elapsed / total)
                
                # Update result duration
                result.duration = current_time - start_time
                progress_callback(progress, result)
    
    except KeyboardInterrupt:
        pass
    finally:
        # Finalize results
        result.duration = time.time() - start_time
        
        # Calculate latency statistics if available
        if latencies:
            result.latency_min_ms = min(latencies)
            result.latency_max_ms = max(latencies)
            result.latency_avg_ms = statistics.mean(latencies)
            
            # Sort for percentiles
            latencies.sort()
            result.latency_p50_ms = latencies[len(latencies) // 2]
            result.latency_p95_ms = latencies[int(len(latencies) * 0.95)]
            result.latency_p99_ms = latencies[int(len(latencies) * 0.99)]
        
        # Flush and stop the sender
        sender.flush()
        sender.stop()
        
        # Wait for cooldown
        if options.cooldown_seconds > 0:
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