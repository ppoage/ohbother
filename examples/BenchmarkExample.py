"""
Example demonstrating benchmarking functionality using ohbother.

This example shows how to run performance tests for packet processing,
including throughput, latency, and scalability measurements.
"""

import sys
import os
import time
from pathlib import Path

# Add the project root directory to Python's path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import from our new library interface
import ohbother
from ohbother.config import Config, create_default_config
from ohbother.benchmark import BenchmarkOptions, PerfTest
from ohbother.receive import receive_packets_by_time

# Network configuration
SRC_MAC = "1a:c0:9f:b8:84:45"
DST_MAC = "3c:7c:3f:86:19:10"
SRC_IP = "192.168.50.105"
DST_IP = "192.168.50.1"
SRC_PORT = 8443
DST_PORT = 8443
INTERFACE = "en0"
BPF_FILTER = f"udp and dst port {DST_PORT}"

# Test parameters
PACKET_COUNT = 5000
PAYLOAD_SIZE = 60
RATE_LIMIT_NS = 1_000_000  # 1ms between packets
SNAP_LEN = 1500
PROMISC = True
BUFFER_SIZE = 4 * 1024 * 1024  # 4MB
IMMEDIATE_MODE = True


def run_simple_benchmark():
    """Run a simple benchmark test using the BenchmarkOptions class."""
    print("\n--- Simple Benchmark Test ---")

    # Create configuration
    config = create_default_config(
        interface=INTERFACE,
        src_mac=SRC_MAC,
        dst_mac=DST_MAC,
        src_ip=SRC_IP,
        dst_ip=DST_IP,
        src_port=SRC_PORT,
        dst_port=DST_PORT,
        bpf_filter=BPF_FILTER,
        snap_len=SNAP_LEN,
        promisc=PROMISC,
        buffer_size=BUFFER_SIZE,
        immediate_mode=IMMEDIATE_MODE
    )

    # Enable debug if desired
    config.debug.enabled = True
    config.debug.level = 2

    # Create benchmark options
    options = BenchmarkOptions(
        packet_size=PAYLOAD_SIZE,
        packet_count=PACKET_COUNT,
        parallel_streams=1,
        warmup_packets=100,
        cooldown_seconds=0.5,
        report_interval=1.0
    )

    # Setup receiver to capture packets (optional)
    receiver = None
    receive_duration = 4.0
    receiver = receive_packets_by_time(config, receive_duration, wait=False)
    time.sleep(0.5)  # Small delay to ensure receiver is ready

    # Define a progress callback
    def progress_callback(progress_pct, partial_results):
        print(f"Progress: {progress_pct:.1f}%, " +
              f"Sent: {partial_results.packets_sent}, " +
              f"Rate: {partial_results.packets_per_second:.0f} pps")

    # Run the benchmark with progress reporting
    print(f"Running benchmark with {PACKET_COUNT} packets of {PAYLOAD_SIZE} bytes...")
    from ohbother.benchmark import run_benchmark
    result = run_benchmark(config, options, progress_callback)

    # Display results
    print(f"\nBenchmark Results:")
    print(f"  Packets sent: {result.packets_sent}")
    print(f"  Bytes sent: {result.bytes_sent}")
    print(f"  Duration: {result.duration:.3f} seconds")
    print(f"  Rate: {result.packets_per_second:.0f} packets/second")
    print(f"  Throughput: {result.send_throughput_mbps:.2f} Mbps")

    # Latency measurements (will only be accurate on loopback interfaces)
    if result.latency_avg_ms > 0:
        print(f"\nLatency Measurements:")
        print(f"  Average: {result.latency_avg_ms:.3f} ms")
        print(f"  Minimum: {result.latency_min_ms:.3f} ms")
        print(f"  Maximum: {result.latency_max_ms:.3f} ms")
        print(f"  p50: {result.latency_p50_ms:.3f} ms")
        print(f"  p95: {result.latency_p95_ms:.3f} ms")
        print(f"  p99: {result.latency_p99_ms:.3f} ms")

    # Check received packets if we set up a receiver
    if receiver:
        packets = receiver.ResultNative()
        print(f"\nReceived {len(packets)} packets")
        if packets:
            print(f"First packet: {bytes(packets[0])[:16]}...")  # Show first 16 bytes


def run_comprehensive_tests():
    """Run a more comprehensive set of performance tests."""
    print("\n--- Comprehensive Performance Tests ---")
    
    # Create configuration
    config = create_default_config(
        interface=INTERFACE,
        src_mac=SRC_MAC,
        dst_mac=DST_MAC,
        src_ip=SRC_IP,
        dst_ip=DST_IP,
        src_port=SRC_PORT,
        dst_port=DST_PORT
    )
    
    # Create a PerfTest instance
    perf = PerfTest(config)
    
    # Run throughput tests with different packet sizes
    print("\nRunning throughput tests with different packet sizes...")
    throughput_results = perf.throughput_test(
        packet_sizes=[64, 512, 1024, 4096],
        duration=2.0,
        parallel_streams=1
    )
    
    # Print summary of throughput tests
    print("\nThroughput Test Summary:")
    print("--------------------------------------------------")
    print("Packet Size | Packets/sec | Throughput (Mbps)")
    print("--------------------------------------------------")
    for size, result in throughput_results.items():
        print(f"{size:11d} | {result.packets_per_second:11.0f} | {result.send_throughput_mbps:15.2f}")
    print("--------------------------------------------------")
    
    # Run latency test if on loopback interface
    if INTERFACE.startswith("lo"):
        print("\nRunning latency test...")
        latency_result = perf.latency_test(packet_count=1000, packet_size=512)
    
    # Run scalability tests with different numbers of streams
    if os.cpu_count() > 2:  # Only if multiple cores are available
        print("\nRunning scalability tests with multiple streams...")
        scalability_results = perf.scalability_test(
            max_streams=4,  # Test up to 4 streams
            packet_size=1024,
            duration=2.0
        )
        
        # Print summary of scalability tests
        print("\nScalability Test Summary:")
        print("--------------------------------------------------")
        print("Streams | Packets/sec | Throughput (Mbps)")
        print("--------------------------------------------------")
        for streams, result in scalability_results.items():
            print(f"{streams:7d} | {result.packets_per_second:11.0f} | {result.send_throughput_mbps:15.2f}")
        print("--------------------------------------------------")


def main():
    """Main function to run benchmark examples."""
    print("OhBother Benchmark Examples")
    
    # Run a simple benchmark
    run_simple_benchmark()
    
    # Uncomment to run comprehensive tests
    # run_comprehensive_tests()


if __name__ == "__main__":
    main()
