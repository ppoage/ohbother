"""
Example demonstrating multi-stream packet transmission using ohbother.

This example shows how to send packets using multiple parallel streams
for maximum throughput.
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
import ohbother
from ohbother.config import Config, create_default_config
from ohbother.config import create_default_config, MultiStreamConfig
from ohbother.transmit import MultiStreamSender
from ohbother.receive import ContinuousPacketReceiver
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

stress_a = True

if stress_a:
    PACKET_COUNT = 35_000_000 #500_000
    #PACKET_COUNT = 25_000_000
    PAYLOAD_SIZE = 60
else:
    PACKET_COUNT = 2_000_000 #500_000
    PAYLOAD_SIZE = 1200

RATE_LIMIT = 200_000

WORKER_COUNT = 12
STREAM_COUNT = 4
SNAP_LEN = 1500
PROMISC = True
BUFFER_SIZE = 1 * 1024 * 1024
IMMEDIATE_MODE = True
RECEIVE_ENABLE = False

# ADD: benchmark decorator at the top of the file
def benchmark(func):
    """Decorator to benchmark a function"""
    def wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        duration = time.perf_counter() - start_time
        print(f"{func.__name__} took {duration:.3f} seconds")
        return result
    return wrapper

# MODIFY: _generate_single_payload function to include timing
def _generate_single_payload(i, size, pattern_type):
    """Helper function to generate a single payload for multiprocessing"""
    start_time = time.perf_counter()
    
    # Original code remains the same
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

    duration = time.perf_counter() - start_time
    return raw_bytes

# MODIFY: generate_pattern_payloads function to include detailed timing
@benchmark
def generate_pattern_payloads(array_length, size, pattern_type="sequence", num_workers=8):
    """Generate payloads in parallel using multiprocessing"""
    t0_setup = time.perf_counter()
    
    # Calculate chunk size for better load balancing
    chunk_size = (array_length + num_workers - 1) // num_workers
    
    print(f"Generating {array_length:,} payloads of size {size} using {num_workers} processes")
    setup_time = time.perf_counter() - t0_setup
    
    # Process in parallel
    t0_pool = time.perf_counter()
    with multiprocessing.Pool(processes=num_workers) as pool:
        raw_payloads = pool.map(
            partial(_generate_single_payload, size=size, pattern_type=pattern_type),
            range(array_length),
        )
    
    pool_time = time.perf_counter() - t0_pool
    
    # Calculate detailed metrics
    total_time = time.perf_counter() - t0_setup
    print(f"Generated {len(raw_payloads):,} payloads in {total_time:.3f}s")
    print(f"Generation rate: {len(raw_payloads)/total_time:,.0f} items/second")
    print(f"  - Setup: {setup_time:.3f}s ({setup_time/total_time*100:.1f}%)")
    print(f"  - Pool execution: {pool_time:.3f}s ({pool_time/total_time*100:.1f}%)")

    return raw_payloads

def process_results(sender, packet_count):
    """Process and display results from the sender."""
    start_time = time.time()
    last_report_time = start_time
    progress_interval = 1.0
    
    # Get initial metrics
    metrics = sender.metrics
    last_packets_sent = metrics["packets_sent"]
    
    while True:
        current_time = time.time()
        # Get latest metrics
        metrics = sender.metrics
        packets_processed = metrics["packets_sent"]
        errors = metrics["errors"]
        
        # Exit when all packets are processed or on error
        if packets_processed >= packet_count:
            break
        if sender.is_complete:
            break
            
        # Report progress periodically
        if current_time - last_report_time >= progress_interval:
            elapsed = current_time - start_time
            pps = packets_processed / elapsed if elapsed > 0 else 0
            interval_pps = (
                (packets_processed - last_packets_sent) / progress_interval
                if progress_interval > 0
                else 0
            )
            percent = (
                (packets_processed / packet_count) * 100 if packet_count > 0 else 0
            )

            print(
                f"Progress: {packets_processed}/{packet_count} ({percent:.1f}%) | "
                f"Rate: {pps:.0f} pps avg, {interval_pps:.0f} pps current | "
                f"Errors: {errors}"
            )

            last_report_time = current_time
            last_packets_sent = packets_processed

        time.sleep(0.01)

    # Get final metrics
    final_metrics = sender.metrics
    final_elapsed = time.time() - start_time
    final_pps = packet_count / final_elapsed if final_elapsed > 0 else 0

    print("\nTransmission complete!")
    print(f"Total packets: {packet_count}")
    print(f"Total bytes: {final_metrics['bytes_sent']} bytes")
    print(f"Total time: {final_elapsed:.2f} seconds")
    print(f"Average rate: {final_pps:.0f} packets per second")
    print(f"Throughput: {final_metrics['bytes_sent']*8/final_elapsed/1_000_000:.2f} Mbps")
    print(f"Errors: {final_metrics['errors']}")
    if "average_latency_ns" in final_metrics:
        print(f"Average latency: {final_metrics['average_latency_ns']/1000:.2f} µs")


def start_receiver(config):
    """Start a receiver in a separate thread."""
    receiver = ContinuousPacketReceiver(config)

    def receive_loop():
        print("Starting receiver...")
        try:
            for packet in receiver:
                # Just count packets, no need to process them in this example
                pass
        except Exception as e:
            print(f"Receiver error: {e}")

    thread = threading.Thread(target=receive_loop, daemon=True)
    thread.start()
    return receiver, thread

# MODIFY: run_multistream function to use timing breakdowns
@benchmark
def run_multistream(
    interface=INTERFACE,
    count=PACKET_COUNT,
    size=PAYLOAD_SIZE,
    pattern="ascending",
    workers=WORKER_COUNT,
    streams=STREAM_COUNT,
    buffer_size=BUFFER_SIZE,
    receive_enable=RECEIVE_ENABLE,
    gen_workers=WORKER_COUNT,
):
    """Run the multi-stream packet sender example."""
    print("MultiStream UDP Packet Sender")
    print(f"Interface: {interface}, Packets: {count}, Size: {size}")
    print(f"Workers: {workers}, Streams: {streams}, Buffer size: {buffer_size}")

    # Create configuration using our new interface
    config = create_default_config(
        interface=interface,
        src_mac=SRC_MAC,
        dst_mac=DST_MAC,
        src_ip=SRC_IP,
        dst_ip=DST_IP,
        src_port=SRC_PORT,
        dst_port=DST_PORT,
        bpf_filter=BPF_FILTER,
        snap_len=SNAP_LEN,
        promisc=PROMISC,
        buffer_size=buffer_size,
        immediate_mode=IMMEDIATE_MODE
    )

    # Optional debugging
    config.debug.enabled = True
    config.debug.level = 4

    # Start receiver if requested
    receiver = None
    if receive_enable:
        receiver, _ = start_receiver(config)

    # Generate payloads (optimized with multiprocessing)
    print(f"Generating {count} payloads of size {size} with pattern '{pattern}'...")
    payloads = generate_pattern_payloads(count, size, pattern, gen_workers)

    # Create multi-stream configuration
    stream_config = MultiStreamConfig(
        packet_workers=workers,
        stream_count=streams,
        channel_buffer_size=1000,
        report_interval=1000,
        enable_cpu_pinning=True,
        disable_ordering=True,
        turnstile_burst=16,
        enable_metrics=False,
        rate_limit=RATE_LIMIT  # No rate limit
    )
    # Create the multi-stream sender
    sender = MultiStreamSender(config, stream_config)

    print(f"Starting transmission of {count} packets...")
    
    # Send the packets across all streams - with detailed timing

    t0_add = time.perf_counter()
    print("Converting and adding payloads to sender...")
    added = sender.add_batch_payloads_flat(payloads, num_workers=workers, perf_measure=True)
    add_time = time.perf_counter() - t0_add
    add_rate = added / add_time if add_time > 0 else 0
    print(f"Payloads added: {added:,} payloads in {add_time:.3f}s ({add_rate:.0f}/s)")

    t0_send = time.perf_counter()
    print("Starting packet transmission...")
    sender.send()
    sender.flush()
    # Process and display results
    process_results(sender, count)
    metrics = sender.metrics
    print(f"Sent {metrics['packets_sent']:,} packets")
    # Display CPU pinning information
    if stream_config.enable_cpu_pinning: print("CPU pinning is enabled")
        
    # Flush remaining packets
    print("Flushing remaining packets...")
    sender.flush()
    
    send_time = time.perf_counter() - t0_send
        
    # Clean up
    if receiver:
        receiver.close()

    # Performance summary
    total_time =  add_time + send_time
    print("\n=== Performance Summary ===")
    print(f"Convert & Addition: {add_time:.3f}s ({add_time/total_time*100:.1f}%)")
    print(f"Sending Time: {send_time:.3f}s ({send_time/total_time*100:.1f}%)")
    print(f"Total throughput: {count/total_time:.0f} packets/second")

    return sender


if __name__ == "__main__":
    import os

    pid = os.getpid()
    print(f"The process ID is: {pid}")
    print(f"The process ID is: {pid}")
    print(f"The process ID is: {pid}")
    run_multistream()
