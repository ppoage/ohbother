package ohbother

import (
	"fmt"
	"time"

	"github.com/gopacket/gopacket"
	"github.com/gopacket/gopacket/layers"
	"github.com/gopacket/gopacket/pcap"
)

// CallReceivePacketsByTime starts a goroutine that collects UDP packets for the specified duration (in seconds).
// It returns two channels: one for the resulting packet payloads (as a slice of []byte) and one for any error.
func callReceivePacketsByTime(cfg *Config, duration float64) (<-chan [][]byte, <-chan error) {
	resultChan := make(chan [][]byte, 1)
	errChan := make(chan error, 1)
	go func() {
		handle, err := pcap.OpenLive(cfg.Pcap.Iface, 65536, true, pcap.BlockForever)
		if err != nil {
			errChan <- fmt.Errorf("error opening interface: %v", err)
			return
		}
		defer handle.Close()

		if cfg.Packet.BPF != "" {
			if err := handle.SetBPFFilter(cfg.Packet.BPF); err != nil {
				errChan <- fmt.Errorf("error setting BPF filter: %v", err)
				return
			}
		}
		packetSource := gopacket.NewPacketSource(handle, handle.LinkType())
		results := [][]byte{}
		timeoutCh := time.After(time.Duration(duration * float64(time.Second)))
		for {
			select {
			case packet := <-packetSource.Packets():
				if packet == nil {
					continue
				}
				udpLayer := packet.Layer(layers.LayerTypeUDP)
				if udpLayer != nil {
					udp, _ := udpLayer.(*layers.UDP)
					// Append the UDP payload directly (as []byte).
					results = append(results, udp.Payload)
				}
			case <-timeoutCh:
				resultChan <- results
				return
			}
		}
	}()
	return resultChan, errChan
}

// CallReceivePacketsByCount starts a goroutine that collects UDP packet payloads until 'count' packets are received.
// If timeout (in seconds) is > 0, the function returns whatever packets have been collected after that duration.
func callReceivePacketsByCount(cfg *Config, count int, timeout float64) (<-chan [][]byte, <-chan error) {
	resultChan := make(chan [][]byte, 1)
	errChan := make(chan error, 1)
	go func() {
		handle, err := pcap.OpenLive(cfg.Pcap.Iface, 65536, true, pcap.BlockForever)
		if err != nil {
			errChan <- fmt.Errorf("error opening interface: %v", err)
			return
		}
		defer handle.Close()

		if cfg.Packet.BPF != "" {
			if err := handle.SetBPFFilter(cfg.Packet.BPF); err != nil {
				errChan <- fmt.Errorf("error setting BPF filter: %v", err)
				return
			}
		}

		packetSource := gopacket.NewPacketSource(handle, handle.LinkType())
		results := [][]byte{}
		var timeoutCh <-chan time.Time
		if timeout > 0 {
			timeoutCh = time.After(time.Duration(timeout * float64(time.Second)))
		}
		for {
			select {
			case packet, ok := <-packetSource.Packets():
				if !ok {
					// Channel closed; return what we have.
					resultChan <- results
					return
				}
				if packet == nil {
					continue
				}
				udpLayer := packet.Layer(layers.LayerTypeUDP)
				if udpLayer != nil {
					udp, _ := udpLayer.(*layers.UDP)
					results = append(results, udp.Payload)
				}
				if len(results) >= count {
					resultChan <- results
					return
				}
			case <-timeoutCh:
				// Timeout reached; return whatever has been collected.
				resultChan <- results
				return
			}
		}
	}()
	return resultChan, errChan
}

// ReceivePacketsByTimeSync is a synchronous wrapper around CallReceivePacketsByTime.
// It collects UDP packets for the specified duration and returns the slice of packet payloads ([]byte) and an error.
func ReceivePacketsByTimeSync(cfg *Config, duration float64) ([][]byte, error) {
	pktChan, errChan := callReceivePacketsByTime(cfg, duration)
	select {
	case packets := <-pktChan:
		return packets, nil
	case err := <-errChan:
		return nil, err
	}
}

// ReceivePacketsByCountSync is a synchronous wrapper around CallReceivePacketsByCount.
// It collects UDP packets until 'count' packets are received or the optional timeout (in seconds) is reached.
func ReceivePacketsByCountSync(cfg *Config, count int, timeout float64) ([][]byte, error) {
	pktChan, errChan := callReceivePacketsByCount(cfg, count, timeout)
	select {
	case packets := <-pktChan:
		return packets, nil
	case err := <-errChan:
		return nil, err
	}
}

// AsyncResult is a composite type that holds the result of an asynchronous receive operation.
type AsyncResult struct {
	Packets [][]byte // The collected packet payloads.
	Err     error    // Any error that occurred.
}

// PacketReceiver wraps asynchronous receive operations.
type PacketReceiver struct {
	resultChan chan [][]byte
	errorChan  chan error
}

// GetPackets returns the collected packet payloads.
func (ar *AsyncResult) GetPackets() [][]byte {
	return ar.Packets
}

// GetErr returns the error, if any.
func (ar *AsyncResult) GetErr() error {
	return ar.Err
}

// PacketReceiverByTime starts an asynchronous receive that collects UDP packet payloads (as [][]byte)
// for the specified duration (in seconds). It immediately returns an PacketReceiver.
func PacketReceiverByTime(cfg *Config, duration float64) *PacketReceiver {
	ar := &PacketReceiver{
		resultChan: make(chan [][]byte, 1),
		errorChan:  make(chan error, 1),
	}
	go func() {
		// Call the helper that returns channels.
		pktChan, errChan := callReceivePacketsByTime(cfg, duration)
		var packets [][]byte
		select {
		case packets = <-pktChan:
			// Got the packets.
		case err := <-errChan:
			ar.errorChan <- err
			return
		}
		ar.resultChan <- packets
	}()
	return ar
}

// PacketReceiverByCount starts an asynchronous receive that collects UDP packet payloads (as [][]byte)
// until 'count' packets are received, or until the optional timeout (in seconds) is reached (if timeout > 0).
func PacketReceiverByCount(cfg *Config, count int, timeout float64) *PacketReceiver {
	ar := &PacketReceiver{
		resultChan: make(chan [][]byte, 1),
		errorChan:  make(chan error, 1),
	}
	go func() {
		pktChan, errChan := callReceivePacketsByCount(cfg, count, timeout)
		var packets [][]byte
		select {
		case packets = <-pktChan:
			// Got packets.
		case err := <-errChan:
			ar.errorChan <- err
			return
		}
		ar.resultChan <- packets
	}()
	return ar
}

// Result blocks until the asynchronous receive operation completes and returns an AsyncResult.
// The returned AsyncResult contains either the slice of packet payloads or an error.
// Otherwise python complains about gopy's returned structure
func (ar *PacketReceiver) Result() *AsyncResult {
	var res AsyncResult
	select {
	case packets := <-ar.resultChan:
		res.Packets = packets
		res.Err = nil
	case err := <-ar.errorChan:
		res.Packets = nil
		res.Err = err
	}
	return &res
}

// ResultNative returns a slice of native []byte values by converting each element
// from the raw [][]byte result. This conversion is done in Go so that Python
// will receive a list of bytes objects (via gopy’s built-in conversion), which you
// can directly use as a bytearray.
func (ar *PacketReceiver) ResultNative() [][]byte {
	res := ar.Result()
	if res.Packets == nil {
		return nil
	}

	// Make deep copies of all packets to ensure memory safety
	packets := make([][]byte, len(res.Packets))
	for i, pkt := range res.Packets {
		packets[i] = make([]byte, len(pkt))
		copy(packets[i], pkt)
	}
	return packets
}

// BytePacket wraps a []byte and is intended to be exposed to Python.
type BytePacket struct {
	Data []byte
}

// NewBytePacket creates a new BytePacket.
func NewBytePacket(data []byte) *BytePacket {
	return &BytePacket{Data: data}
}

// GetData returns the underlying []byte. With PR #342 in gopy, this should be
// converted automatically to a native Python bytes object.
func (bp *BytePacket) GetData() []byte {
	return bp.Data
}
