import sys
import os
import time
import argparse
import threading

# Add the project root directory to Python's path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Dev Imports
dev_env = False
if dev_env:
    from ..src.ohbother.ohbother import ohbother as pooh
    from ohbother import Slice_byte
else:
    from ohbother import ohbother as pooh
    from ohbother.go import Slice_byte
import random, time
import threading

sliceByte = pooh.go.Slice_byte

# Default configuration values
srcMAC = "1a:c0:9f:b8:84:45" #"80:a9:97:19:c7:e7" 
dstMAC = "3c:7c:3f:86:19:10"
srcIP = "192.168.50.105"
dstIP = "192.168.50.1"
srcPort = 8443
dstPort = 8443
iface = "en0"
bpf = f"udp and dst port {dstPort}"
packetCount = 500000
payloadSize = 600
rateLimit = 200000
SnapLen = 1500
Promisc = True
BufferSize = 1 * 4 * 1024  # or 4MB
ImmediateMode = True
recieveEnable = False
workerCount = 4
streamCount = 2

def generate_pattern_payload(array_length: int, size: int, pattern_type="sequence") -> list[bytes]:
    """Generate an array of patterned payloads for testing."""
    payloads = []
    
    for i in range(array_length):
        if pattern_type == "sequence":
            # Create a repeating sequence 0,1,2...255,0,1,...
            raw_bytes = bytes([j % 256 for j in range(size)])
        elif pattern_type.startswith("fixed:"):
            # Set all bytes to the specified value
            value_str = pattern_type.split(":")[1]
            # Handle hexadecimal values
            if value_str.startswith("0x") or all(c in "0123456789ABCDEFabcdef" for c in value_str) and len(value_str) >= 2:
                try:
                    # Try to parse as hex
                    if value_str.startswith("0x"):
                        value = int(value_str, 16)
                    else:
                        value = int(value_str, 16)
                except ValueError:
                    # Fall back to decimal if hex parsing fails
                    value = int(value_str)
            else:
                # Parse as decimal
                value = int(value_str)
            # Ensure value is in valid byte range (0-255)
            value = value & 0xFF
            raw_bytes = bytes([value] * size)
        elif pattern_type == "ascending":
            # Each packet starts with a different value
            raw_bytes = bytes([(j + i) % 256 for j in range(size)])
        elif pattern_type == "zeroes":
            # All bytes set to 0
            raw_bytes = bytes([0] * size)
        else:
            # Default to sequence if invalid pattern type
            print("Invalid pattern type, defaulting to sequence")
            raw_bytes = bytes([j % 256 for j in range(size)])
            
        payloads.append(sliceByte.from_bytes(raw_bytes))
    return payloads

def process_results(sender, packet_count):
    """Process and display results from the sender."""
    start_time = time.time()
    last_report_time = start_time
    progress_interval = 1.0  # Report every second
    
    # Track statistics
    packets_processed = 0
    errors = 0
    last_packets = 0
    
    # Process results as they arrive
    while not sender.IsComplete():
        current_time = time.time()
        
        # Get any available results
        result = sender.GetNextResult()
        if result:
            packets_processed = result.Index + 1
            
            # Check for errors
            # if result and result.Error != "":
            #     errors += 1
            #     print(f"Error on packet {result.Index}: {result.Error}")
        
        # Report progress periodically
        if current_time - last_report_time >= progress_interval:
            elapsed = current_time - start_time
            pps = packets_processed / elapsed if elapsed > 0 else 0
            interval_pps = (packets_processed - last_packets) / progress_interval if progress_interval > 0 else 0
            percent = (packets_processed / packet_count) * 100 if packet_count > 0 else 0
            
            print(f"Progress: {packets_processed}/{packet_count} ({percent:.1f}%) | Rate: {pps:.0f} pps avg, {interval_pps:.0f} pps current | Errors: {errors}")
            
            last_report_time = current_time
            last_packets = packets_processed
            
        # Don't hog CPU
        time.sleep(0.005)
    
    # Get final statistics
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
            # Process packets if needed
            # print(f"Got packet: {len(packet.Payload)} bytes from {packet.SrcIP}:{packet.SrcPort}")
    
    thread = threading.Thread(target=receive_loop)
    thread.daemon = True
    thread.start()
    return receiver, thread

def main():
    # Parse command-line arguments for customization
    parser = argparse.ArgumentParser(description="MultiStream UDP Packet Sender Example")
    parser.add_argument("--interface", default=iface, help=f"Network interface (default: {iface})")
    parser.add_argument("--count", type=int, default=packetCount, help=f"Number of packets (default: {packetCount})")
    parser.add_argument("--size", type=int, default=payloadSize, help=f"Payload size in bytes (default: {payloadSize})")
    parser.add_argument("--rate", type=int, default=rateLimit, help=f"Rate limit in packets/sec (default: {rateLimit})")
    parser.add_argument("--pattern", default="sequence", help="Payload pattern (sequence, fixed:X, ascending, zeroes)")
    parser.add_argument("--workers", type=int, default=workerCount, help="Number of packet preparation workers (default: 8)")
    parser.add_argument("--streams", type=int, default=streamCount, help="Number of sending streams (default: 4)")
    parser.add_argument("--buffers", type=int, default=BufferSize, help="Channel buffer size (default: 1000)")
    parser.add_argument("--receive", action="store_true", help="Also start a packet receiver")
    args = parser.parse_args()
    
    print("MultiStream UDP Packet Sender Example")
    print(f"Interface: {args.interface}, Packets: {args.count}, Size: {args.size}, Rate: {args.rate}")
    print(f"Workers: {args.workers}, Streams: {args.streams}, Buffers: {args.buffers}")
    print(f"Pattern: {args.pattern}, Receive: {args.receive}")
    
    # Create configuration
    config = pooh.NewDefaultConfig(iface, srcMAC, dstMAC, srcIP, dstIP, srcPort, dstPort, bpf, SnapLen, Promisc, BufferSize, ImmediateMode)


    
    # Enable Debug for verbose output
    config.Debug.Enabled = True
    config.Debug.Level = 3  # Detailed debug
    
    # Start receiver if requested
    receiver = None
    if args.receive:
        config.Pcap.Filter = bpf
        receiver, _ = start_receiver(config)
        print(f"Receiver started with filter: {bpf}")
    
    # Generate payloads
    print(f"Generating {args.count} payloads of size {args.size} with pattern '{args.pattern}'...")
    payloads = generate_pattern_payload(args.count, args.size, args.pattern)
    print(f"Generated {len(payloads)} payloads")
    
    # Create MultiStreamSender
    sender = pooh.NewMultiStreamSender(config, args.rate)
    
    # Configure the stream parameters
    sender.SetStreamConfig(args.workers, args.streams, args.buffers, 1000)
    
    # Add payloads to the sender
    print("Adding payloads to sender...")
    for payload in payloads:
        sender.AddPayload(payload)
    
    # Send packets
    print(f"Starting transmission of {args.count} packets...")
    sender.Send()
    
    # Process results and display statistics
    process_results(sender, args.count)
    
    # Clean up
    if receiver:
        receiver.Close()
    
    print("Example complete.")

if __name__ == "__main__":
    main()