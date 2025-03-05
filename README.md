# ohbother

A high-performance UDP packet transmitter/receiver built in Go with Python bindings using [gopacket](https://github.com/gopacket/gopacket).

## Installation

```bash
(future work) pip install ohbother
```

You can also build from source:
```git clone https://github.com/ppoage/ohbother.git
cd ohbother
python src/build.py bdist_wheel
pip install dist/*.whl
```

## Usage

Import the package as follows:
```import ohbother as pooh
from ohbother.go import Slice_byte
```

## Basic Example
```import ohbother as pooh
import time

# Network configuration
# Network configuration
iface = "en0"  # or "eth0" on Linux, "Ethernet" on Windows
srcMAC = "00:00:00:00:00:00"  # Your source MAC (defaults to interface MAC)
dstMAC = "ff:ff:ff:ff:ff:ff"  # Destination MAC (defaults to broadcast)
srcIP = "0.0.0.0"  # Source IP (defaults to interface IP)
dstIP = "255.255.255.255"  # Destination IP (defaults to broadcast)
srcPort = 12345  # Source UDP port
dstPort = 12345  # Destination UDP port
bpf = f"udp and dst port {dstPort}"  # Berkeley Packet Filter

# Create a configuration object
config = pooh.NewDefaultConfig(
    iface,
    srcMAC, dstMAC,
    srcIP, dstIP,
    srcPort, dstPort,
    bpf,
    1500,  # SnapLen
    True,  # Promisc
    65536, # BufferSize
    False  # ImmediateMode
)

# Enable debug if needed
config.EnableDebug(0)  # 0=none, 1=info, 2=debug, 3=verbose

# Send a packet
payload = b"Hello, world!"
pooh.SendPacket(config, payload, 0)  # 0 rate limit means no rate limiting

# Start a receiver for 5 seconds
receiver = pooh.PacketReceiverByTime(config, 5.0)
time.sleep(5.1)  # Wait for receiver to finish

# Get received packets
packets = receiver.ResultNative()
print(f"Received {len(packets)} packets")
```

## High-Throughput Example

For sending large numbers of packets:
```import ohbother as pooh
import time
import threading

# Create your config
config = pooh.NewDefaultConfig(...)

# Set up receiver
receiver = pooh.PacketReceiverByTime(config, 4.0)

# Create a sender with rate limiting (packets per second)
sender = pooh.NewPacketSequenceSender(config, 1000000)  # 1M packets/sec max
sender.EnableBatchMode(100)  # Process in batches of 100

# Add multiple payloads
payloads = [b"Payload " + str(i).encode() for i in range(10000)]
for payload in payloads:
    sender.AddPayload(payload)

# Start sending (non-blocking)
sender.StartSending()

# Wait for completion
sender.Wait()

# Get statistics
sent = sender.GetSentCount()
errors = sender.GetErrorCount()
print(f"Sent: {sent}, Errors: {errors}")

# Get received packets
packets = receiver.ResultNative()
print(f"Received {len(packets)} packets")
```

## API Reference

### Configuration

NewDefaultConfig(iface, srcMAC, dstMAC, srcIP, dstIP, srcPort, dstPort, bpf, snapLen, promisc, bufferSize, immediateMode): Create a new configuration
config.EnableDebug(level): Set debug level (0=none, 1=info, 2=debug, 3=verbose)

### Sending

SendPacket(config, payload, rateLimit): Send a single packet
SendPackets(config, payloads, rateLimit): Send multiple packets
NewPacketSequenceSender(config, rateLimit): Create a high-performance sender
AddPayload(payload): Add a payload to send
StartSending(): Start sending (non-blocking)
Wait(): Wait for completion
GetSentCount(): Get number of sent packets
GetErrorCount(): Get number of errors

### Receiving

PacketReceiverByTime(config, duration): Receive packets for a specified duration
PacketReceiverByCount(config, count, timeout): Receive a specific number of packets
ResultNative(): Get received packets as a list of byte arrays

### Features
High Performance: Written in Go for maximum speed
Rate Limiting: Control packet transmission rates
Flexible API: Simple interface for both basic and advanced use cases
Cross-Platform: Works on Linux, macOS, and Windows
Low Overhead: Minimal processing between your code and the network

### Requirements
Python 3.10+
Go 1.24+ (for building from source)
libpcap development headers (for Linux)
npcap/winpcap .dll in sys32 or /user folder (for Windows)