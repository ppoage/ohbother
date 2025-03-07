import sys
import os
import time
import threading
import multiprocessing
from functools import partial

# Add the project root directory to Python's path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import ohbother package
from ohbother import ohbother as pooh
from ohbother.go import Slice_byte

# Network configuration
srcMAC = "1a:c0:9f:b8:84:45"
dstMAC = "3c:7c:3f:86:19:10"
srcIP = "192.168.50.105"
dstIP = "192.168.50.1"
srcPort = 8443
dstPort = 8443
iface = "en0"
bpf = f"udp and dst port {dstPort}"
packetCount = 10
payloadSize = 60 #1458
rateLimit = 0
SnapLen = 1500
Promisc = True
BufferSize = 1 * 1024 * 1024
ImmediateMode = True
workerCount = 12
streamCount = 6


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

    return raw_bytes


def generate_pattern_payload(
    array_length, size, pattern_type="sequence", num_workers=8
):
    """Generate payloads in parallel using multiprocessing"""
    with multiprocessing.Pool(processes=num_workers) as pool:
        raw_payloads = pool.map(
            partial(_generate_single_payload, size=size, pattern_type=pattern_type),
            range(array_length),
        )

    return [Slice_byte.from_bytes(payload) for payload in raw_payloads]


def process_results(sender, packet_count):
    """Process and display results from the sender."""
    start_time = time.time()
    last_report_time = start_time
    progress_interval = 1.0

    packets_processed = 0
    errors = 0
    last_packets = 0

    while not sender.IsComplete():
        current_time = time.time()

        result = sender.GetNextResult()
        if result:
            packets_processed = result.Index + 1

        if current_time - last_report_time >= progress_interval:
            elapsed = current_time - start_time
            pps = packets_processed / elapsed if elapsed > 0 else 0
            interval_pps = (
                (packets_processed - last_packets) / progress_interval
                if progress_interval > 0
                else 0
            )
            percent = (
                (packets_processed / packet_count) * 100 if packet_count > 0 else 0
            )

            print(
                f"Progress: {packets_processed}/{packet_count} ({percent:.1f}%) | Rate: {pps:.0f} pps avg, {interval_pps:.0f} pps current | Errors: {errors}"
            )

            last_report_time = current_time
            last_packets = packets_processed

        time.sleep(0.005)

    final_elapsed = time.time() - start_time
    final_pps = packet_count / final_elapsed if final_elapsed > 0 else 0

    print("\nTransmission complete!")
    print(f"Total packets: {packet_count}")
    print(f"Total time: {final_elapsed:.2f} seconds")
    print(f"Average rate: {final_pps:.0f} packets per second")
    print(f"Errors: {errors}")


def start_receiver(config):
    """Start a receiver in a separate thread."""
    receiver = pooh.NewReceiver(config)

    def receive_loop():
        print("Starting receiver...")
        while True:
            packet = receiver.GetNextPacket()
            if not packet:
                break

    thread = threading.Thread(target=receive_loop)
    thread.daemon = True
    thread.start()
    return receiver, thread


def run_multistream(
    interface=iface,
    count=packetCount,
    size=payloadSize,
    rate=rateLimit,
    pattern="ascending",
    workers=workerCount,
    streams=streamCount,
    buffers=BufferSize,
    receive_enable=False,
    gen_workers=8,
):
    print("MultiStream UDP Packet Sender")
    print(f"Interface: {interface}, Packets: {count}, Size: {size}, Rate: {rate}")
    print(f"Workers: {workers}, Streams: {streams}, Buffers: {buffers}")

    config = pooh.NewDefaultConfig(
        interface,
        srcMAC,
        dstMAC,
        srcIP,
        dstIP,
        srcPort,
        dstPort,
        bpf,
        SnapLen,
        Promisc,
        buffers,
        ImmediateMode,
    )

    # Optional debugging
    config.Debug.Enabled = True
    config.Debug.Level = 3

    # Start receiver if requested
    receiver = None
    if receive_enable:
        config.Pcap.Filter = bpf
        receiver, _ = start_receiver(config)

    # Generate payloads (optimized with multiprocessing)
    print(f"Generating {count} payloads of size {size} with pattern '{pattern}'...")
    start_gen = time.time()
    payloads = generate_pattern_payload(count, size, pattern, gen_workers)
    gen_time = time.time() - start_gen
    print(
        f"Generated {len(payloads)} payloads in {gen_time:.2f}s ({count/gen_time:.0f} payloads/sec)"
    )

    # Create and configure sender
    sender = pooh.NewMultiStreamSender(config, rate)
    sender.SetStreamConfig(
        packetWorkers=12,     # Number of worker goroutines for packet preparation
        streamCount=6,        # Number of parallel sending streams
        channelBuffers=10000, # Size of channel buffers
        reportInterval=5000   # How often to report progress
    )

    # Advanced configuration
    sender.SetAdvancedConfig(
        enableCPUPinning=True,   # Pin threads to CPU cores for better performance
        disableOrdering=False,   # Keep packet ordering intact
        turnstileBurst=10,       # Allow bursts of 10 packets in the rate limiter
        enableMetrics=True       # Collect performance metrics
    )

    # Add payloads to the sender
    print("Adding payloads to sender...")
    for payload in payloads:
        sender.AddPayload(payload)

    # Send packets
    print(f"Starting transmission of {count} packets...")
    sender.Send()

    # Check configuration
    if sender.IsOrderingEnabled():
        print("Packet ordering is enabled")

    # Get metrics after sending
    if sender.AreMetricsEnabled():
        metrics = sender.GetMetrics()
        print(f"Average packet preparation time: {metrics['avg_prepare_ns']} ns")

    # Process results
    process_results(sender, count)

    # Clean up
    if receiver:
        receiver.Close()

    return sender


if __name__ == "__main__":
    run_multistream()
