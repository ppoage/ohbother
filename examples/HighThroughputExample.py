from functools import partial
import multiprocessing
import sys
import os

# Add the project root directory to Python's path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ohbother import ohbother as pooh
from ohbother.go import Slice_byte

import random, time
import threading

sliceByte = pooh.go.Slice_byte

srcMAC = "1a:c0:9f:b8:84:45" #"80:a9:97:19:c7:e7" 
dstMAC = "3c:7c:3f:86:19:10"
srcIP = "192.168.50.105"
dstIP = "192.168.50.1"
srcPort = 8443
dstPort = 8443
iface = "en0"
bpf = f"udp and dst port {dstPort}"
packetCount = 500_000
payloadSize = 60
rateLimit = 0#1_000_000
SnapLen =      1500 #1500
Promisc =       True
#Timeout =       10 * (0.001)
BufferSize =    4 * 1024 * 1024 # 4MB
ImmediateMode = True
recieveEnable = False


def _generate_single_payload(i, size, pattern_type):
    """Helper function to generate a single payload for multiprocessing"""
    if pattern_type == "sequence":
        raw_bytes = bytes([j % 256 for j in range(size)])
    elif pattern_type.startswith("fixed:"):
        value_str = pattern_type.split(":")[1]
        try:
            value = int(value_str, 16) if (value_str.startswith("0x") or all(c in "0123456789ABCDEFabcdef" for c in value_str)) else int(value_str)
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

def generate_pattern_payload(array_length, size, pattern_type="sequence", num_workers=8):
    """Generate payloads in parallel using multiprocessing"""
    with multiprocessing.Pool(processes=num_workers) as pool:
        raw_payloads = pool.map(
            partial(_generate_single_payload, size=size, pattern_type=pattern_type),
            range(array_length)
        )
    
    return [Slice_byte.from_bytes(payload) for payload in raw_payloads]

def main():
    receive_duration = 4.0

    config = pooh.NewDefaultConfig(iface, srcMAC, dstMAC, srcIP, dstIP, srcPort, dstPort, bpf, SnapLen, Promisc, BufferSize, ImmediateMode)
    config.EnableDebug(0)

    # Generate test payload
    testPayload = generate_pattern_payload(packetCount, payloadSize, "fixed:F0")
    
    # Setup receiver
    if recieveEnable: asyncRecv = pooh.PacketReceiverByTime(config, receive_duration)
    # Adding small delay to ensure the receiver is ready for a short sequence
    time.sleep(0.5)

    # Create a sender
    sender = pooh.NewPacketSequenceSender(config, rateLimit)
    # sender.EnableBatchMode(1)  # Process results in batches of 100

    # Add payloads
    for payload in testPayload:
        sender.AddPayload(payload)

    # Set up counters
    sent_count = 0
    errors = 0
    
    # Use a lock to protect the counters
    counter_lock = threading.Lock()
    
    # Create a thread to receive results
    def receive_results():
        nonlocal sent_count, errors
        while not sender.IsComplete():
            result = sender.GetNextResult()
            if result is None:
                break
            
            with counter_lock:
                sent_count += 1
                if result.GetError():
                    errors += 1

    # Start timing
    start_time_ns = time.perf_counter_ns()
    
    # Start the receiver thread first
    receiver_thread = threading.Thread(target=receive_results)
    receiver_thread.start()
    
    # Start sending (non-blocking) - ONLY CALL THIS ONCE
    sender.Send()

    # Wait for completion
    receiver_thread.join()

    # Measure total elapsed time
    end_time_ns = time.perf_counter_ns()
    total_send_time_ns = end_time_ns - start_time_ns
    total_send_time = total_send_time_ns / 1e9  # Convert to seconds for display

    # Display simple statistics
    print(f"\nTransmission Results:")
    print(f"  Total packets: {sent_count}")
    print(f"  Total time: {total_send_time:.6f}s")
    print(f"  Rate: {sent_count/total_send_time:.2f} packets/sec")
    
    # Retrieve received packets
    if recieveEnable: packets = asyncRecv.ResultNative()
    if recieveEnable: print(f"Received {len(packets)} packets")
    if recieveEnable and packets:
        print(f"First packet: {bytes(packets[0])[:16]}...")  # Show first 16 bytes

if __name__ == "__main__":
    print("running")
    main()