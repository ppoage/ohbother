"""
Example demonstrating high-throughput packet transmission using ohbother.

This example shows how to send multiple packets in sequence with optional
rate limiting and measure the performance.
"""

import sys
import os
import time
import threading
import multiprocessing
from functools import partial

# Add the project root directory to Python's path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import from our new library interface
import ohbother as Pooh
from ohbother.config import Config, create_default_config
from ohbother.transmit import PacketSequenceSender
from ohbother.receive import receive_packets_by_time
from ohbother.utilities import pass_bytes_to_go

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
PACKET_COUNT = 5
PAYLOAD_SIZE = 60
RATE_LIMIT_NS = 0  # 0 = no rate limiting, or use value like 1_000_000 (1ms)
SNAP_LEN = 1500
PROMISC = True
BUFFER_SIZE = 4 * 1024 * 1024  # 4MB
IMMEDIATE_MODE = True
RECEIVE_ENABLE = False


def _generate_single_payload(i, size, pattern_type):
    """Helper function to generate a single payload for multiprocessing"""
    if pattern_type == "sequence":
        raw_bytes = bytes([j % 256 for j in range(size)])
    elif pattern_type.startswith("fixed:"):
        value_str = pattern_type.split(":")[1]
        try:
            value = (
                int(value_str, 16)
                if (
                    value_str.startswith("0x")
                    or all(c in "0123456789ABCDEFabcdef" for c in value_str)
                )
                else int(value_str)
            )
        except ValueError:
            value = 0
        raw_bytes = bytes([value & 0xFF] * size)
    elif pattern_type == "ascending":
        raw_bytes = bytes([(j + i) % 256 for j in range(size)])
    elif pattern_type == "zeroes":
        raw_bytes = bytes(size)  # More efficient than bytes([0] * size)
    else:
        raw_bytes = bytes([j % 256 for j in range(size)])
    
    return bytearray(raw_bytes)


def generate_pattern_payloads(array_length, size, pattern_type="sequence", num_workers=8):
    """Generate payloads in parallel using multiprocessing"""
    with multiprocessing.Pool(processes=num_workers) as pool:
        raw_payloads = pool.map(
            partial(_generate_single_payload, size=size, pattern_type=pattern_type),
            range(array_length),
        )

    return raw_payloads  # Return raw bytes, don't convert to Slice_byte yet


def main():
    receive_duration = 4.0

    # Create configuration using our new interface
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
    
    # Enable debug if needed
    config.debug.enabled = False
    config.debug.level = 0

    # Generate test payloads
    test_payloads = generate_pattern_payloads(PACKET_COUNT, PAYLOAD_SIZE, "fixed:F0")
    for i, payload in enumerate(test_payloads):
        print(f"Payload {i}: {bytes(payload[:16])}...")  # Show first 16 bytes

    # Setup receiver if enabled
    receiver = None
    if RECEIVE_ENABLE:
        # Using non-waiting receiver to start in background
        receiver = receive_packets_by_time(config, receive_duration, wait=False)
    
    # Adding small delay to ensure the receiver is ready for a short sequence
    time.sleep(0.5)

    # Create a sender using our new interface
    sender = PacketSequenceSender(config, interval_ns=RATE_LIMIT_NS)

    # Add payloads to the sequence
    for payload in test_payloads:
        sender.add_packet(payload)

    print(f"\nSending {sender.count} packets...")
    
    # Start timing
    start_time = time.perf_counter()
    
    # Send all packets and get results
    results = sender.send()
    
    # Calculate elapsed time
    end_time = time.perf_counter()
    total_send_time = end_time - start_time

    # Count successful sends
    successful_sends = sum(1 for r in results if results)
    errors = sum(1 for r in results if not results)
    
    # Display statistics
    print(f"\nTransmission Results:")
    print(f"  Total packets: {len(results)}")
    print(f"  Successful: {successful_sends}")
    print(f"  Errors: {errors}")
    print(f"  Total time: {total_send_time:.6f}s")
    print(f"  Rate: {len(results)/total_send_time:.2f} packets/sec")
    
    # If bytes were sent, show the average bytes per packet
    # total_bytes = sum(r.bytes_sent for r in results)
    # if total_bytes > 0:
    #     print(f"  Average bytes per packet: {total_bytes/len(results):.2f}")
    #     print(f"  Total throughput: {total_bytes*8/total_send_time/1_000_000:.2f} Mbps")

    # Retrieve received packets if enabled
    if RECEIVE_ENABLE and receiver:
        packets = receiver.ResultNative()
        print(f"\nReceived {len(packets)} packets")
        if packets:
            print(f"First packet: {bytes(packets[0])[:16]}...")  # Show first 16 bytes


if __name__ == "__main__":
    print("Running high throughput example...")
    main()
