from ohbother import ohbother as pooh
from ohbother.go import Slice_byte
import random, time


srcMAC = "1a:c0:9f:b8:84:45"  # "80:a9:97:19:c7:e7"
dstMAC = "3c:7c:3f:86:19:10"
srcIP = "192.168.50.105"
dstIP = "192.168.50.1"
srcPort = 8443
dstPort = 8443
iface = "en0"
bpf = f"udp and dst port {dstPort}"
packetCount = 5000
payloadSize = 60
rateLimit = 1_000_000
SnapLen = 1500  # 1500
Promisc = True
# Timeout =       10 * (0.001)
BufferSize = 4 * 1024 * 1024  # 4MB
ImmediateMode = True


def main():
    receive_duration = 4.0

    config = pooh.NewDefaultConfig(
        iface,
        srcMAC,
        dstMAC,
        srcIP,
        dstIP,
        srcPort,
        dstPort,
        bpf,
        SnapLen,
        Promisc,
        BufferSize,
        ImmediateMode,
    )
    config.EnableDebug(3)

    # Generate test payload

    # Setup receiver
    asyncRecv = pooh.PacketReceiverByTime(config, receive_duration)
    # Adding small delay to ensure the receiver is ready for a short sequence
    time.sleep(0.5)

    # Create a sender
    sender = pooh.BenchmarkSend(config, packetCount, payloadSize, rateLimit)
    print(f"Sent {packetCount} packets at {sender:0.1f} packets/sec")

    # Retrieve received packets
    packets = asyncRecv.ResultNative()
    print(f"Received {len(packets)} packets")
    if packets:
        print(f"First packet: {bytes(packets[0])[:16]}...")  # Show first 16 bytes


if __name__ == "__main__":
    print("running")
    main()
