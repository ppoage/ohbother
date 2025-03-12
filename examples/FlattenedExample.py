#!/usr/bin/env python3
"""
Example demonstrating the flattened approach for efficient data transfer.

This script shows how to use the flattened approach to efficiently transfer
large amounts of data from Python to Go, which can significantly improve
performance for large datasets.
"""

import os
import sys
import time
import random
from typing import List

import ohbother
from ohbother.config import create_default_config, MultiStreamConfig
from ohbother.transmit import MultiStreamSender

SRC_MAC = "1a:c0:9f:b8:84:45"
DST_MAC = "3c:7c:3f:86:19:10"
SRC_IP = "192.168.50.105"
DST_IP = "192.168.50.1"
SRC_PORT = 8443
DST_PORT = 8443
INTERFACE = "en0"
BPF_FILTER = f"udp and dst port {DST_PORT}"


def generate_test_data(count: int, size: int) -> List[bytes]:
    """Generate random byte arrays for testing."""
    print(f"Generating {count:,} random byte arrays of size {size} bytes...")
    start_time = time.time()
    
    # Generate data
    data = [os.urandom(size) for _ in range(count)]
    
    duration = time.time() - start_time
    print(f"Generated {count:,} arrays in {duration:.2f} seconds ({count/duration:,.0f} arrays/second)")
    
    return data

def run_standard_approach(config, stream_config, data: List[bytes]):
    """Run test using the standard approach."""
    print("\n=== Standard Approach ===")
    
    # Create sender with stream configuration
    sender = MultiStreamSender(config, stream_config)
    
    # Add payloads using standard approach
    start_time = time.time()
    added = sender.add_batch_payloads(data)
    add_time = time.time() - start_time
    
    print(f"Added {added:,} payloads in {add_time:.2f} seconds ({added/add_time:,.0f} payloads/second)")
    
    # Send the payloads
    print("Sending payloads...")
    sender.send()
    
    # Wait for completion
    sender.flush()
    
    # Get metrics
    metrics = sender.metrics
    print(f"Sent {metrics['packets_sent']:,} packets")
    
    return add_time

def run_flattened_approach(config, stream_config, data: List[bytes]):
    """Run test using the flattened approach."""
    print("\n=== Flattened Approach ===")
    
    # Create sender with stream configuration
    sender = MultiStreamSender(config, stream_config)
    
    # Add payloads using flattened approach
    start_time = time.time()
    added = sender.add_batch_payloads_flat(data)
    add_time = time.time() - start_time
    
    print(f"Added {added:,} payloads in {add_time:.2f} seconds ({added/add_time:,.0f} payloads/second)")
    
    # Send the payloads
    print("Sending payloads...")
    sender.send()
    
    # Wait for completion
    # while not sender.is_complete:
        
    #     pass

    # for i in range(5):
    #     if sender.is_complete:
    #         break
    #     print(f"Done: {sender.is_complete} Waiting for completion...")
    #     time.sleep(1)
    
    sender.flush()
    
    # Get metrics
    metrics = sender.metrics
    print(f"Sent {metrics['packets_sent']:,} packets")
    
    return add_time

def main():
    """Run the example."""
    # Create a default configuration
    config = create_default_config(
        interface=INTERFACE,  # Use loopback interface
        src_mac=SRC_MAC,
        dst_mac=DST_MAC,
        bpf_filter=BPF_FILTER,

        src_ip=SRC_IP,
        dst_ip=DST_IP,
        src_port=SRC_PORT,
        dst_port=DST_PORT,
    )
    
    # Configure multi-stream settings
    stream_config = MultiStreamConfig(
        packet_workers=8,
        stream_count=4,
        channel_buffer_size=1000,
        report_interval=10000,
        enable_cpu_pinning=True,
        disable_ordering=True,
        turnstile_burst=16,
        enable_metrics=True,
        rate_limit=0  # No rate limit
    )
    
    # Note: Don't set config.stream_config directly, pass it to MultiStreamSender constructor
    
    # Test parameters
    item_count = 40_000_000  # 1 million items
    item_size = 64          # 64 bytes per item
    
    print(f"Testing with {item_count:,} items of {item_size} bytes each")
    print(f"Total data size: {(item_count * item_size) / (1024**2):.2f} MB")
    
    # Generate test data
    data = generate_test_data(item_count, item_size)
    
    # Run tests
    #standard_time = run_standard_approach(config, stream_config, data)
    flattened_time = run_flattened_approach(config, stream_config, data)
    
    # Compare results
    # speedup = standard_time / flattened_time if flattened_time > 0 else 0
    # print("\n=== Performance Comparison ===")
    # print(f"Standard approach: {standard_time:.2f} seconds")
    print(f"Flattened approach: {flattened_time:.2f} seconds")
    # print(f"Speedup: {speedup:.2f}x")
    
    # if speedup > 1:
    #     print(f"The flattened approach was {speedup:.2f}x faster!")
    # else:
    #     print("The standard approach was faster in this test.")
    #     print("Note: The flattened approach typically shows better performance with larger datasets.")

if __name__ == "__main__":
    main()
