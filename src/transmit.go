package ohbother

import (
	"context"
	"fmt"
	"net"
	"reflect"
	"time"

	"github.com/gopacket/gopacket"
	"github.com/gopacket/gopacket/layers"
	"github.com/gopacket/gopacket/pcap"
	"golang.org/x/time/rate"
)

func sendSinglePacket(handle *pcap.Handle, cfg *Config, payload []byte) error {
	// Use the logger if debugging is enabled
	if cfg.Debug.Enabled && cfg.Debug.Level >= 3 {
		cfg.Debug.Logger.Debug("sendSinglePacket called")
		cfg.Debug.Logger.Debug("Source MAC: %s", cfg.Packet.SrcMAC)
		cfg.Debug.Logger.Debug("Dest MAC: %s", cfg.Packet.DstMAC)
	}

	// Minimum packet size check
	minPayloadSize := 18
	if len(payload) < minPayloadSize {
		err := fmt.Errorf("payload size %d is below minimum required size of %d bytes",
			len(payload), minPayloadSize)
		if cfg.Debug.Enabled && cfg.Debug.Level >= 1 {
			cfg.Debug.Logger.Error("%v", err)
		}
		return err
	}

	// Ethernet layer.
	eth := layers.Ethernet{
		SrcMAC:       cfg.Packet.SrcMAC,
		DstMAC:       cfg.Packet.DstMAC,
		EthernetType: layers.EthernetTypeIPv4,
	}

	// IPv4 layer.
	ip := layers.IPv4{
		Version:  4,
		IHL:      5,
		TTL:      64,
		Protocol: layers.IPProtocolUDP,
		SrcIP:    net.ParseIP(cfg.Packet.SrcIP),
		DstIP:    net.ParseIP(cfg.Packet.DstIP),
	}

	// Verify IP addresses were parsed correctly
	LogDebug("  - Parsed Source IP: %s\n", ip.SrcIP)
	LogDebug("  - Parsed Dest IP: %s\n", ip.DstIP)

	// UDP layer.
	udp := layers.UDP{
		SrcPort: layers.UDPPort(cfg.Packet.SrcPort),
		DstPort: layers.UDPPort(cfg.Packet.DstPort),
	}
	LogDebug("  - UDP Ports: %d -> %d\n", udp.SrcPort, udp.DstPort)

	// Compute UDP checksum over the IPv4 pseudo-header.
	if err := udp.SetNetworkLayerForChecksum(&ip); err != nil {
		LogError("Checksum calculation failed: %v\n", err)
		return fmt.Errorf("failed to set network layer for checksum: %v", err)
	}

	// Serialize the packet.
	buffer := gopacket.NewSerializeBuffer()
	opts := gopacket.SerializeOptions{FixLengths: true, ComputeChecksums: true}
	if err := gopacket.SerializeLayers(buffer, opts,
		&eth,
		&ip,
		&udp,
		gopacket.Payload(payload),
	); err != nil {
		LogError("Packet serialization failed: %v\n", err)
		return fmt.Errorf("failed to serialize packet: %v", err)
	}

	// Debug serialized packet
	packetBytes := buffer.Bytes()
	LogDebug("  - Total packet size: %d bytes\n", len(packetBytes))

	// Verify captured link type matches what we're sending
	LogDebug("  - Handle link type: %v\n", handle.LinkType())

	// Send the packet.
	if err := handle.WritePacketData(packetBytes); err != nil {
		LogError("Packet transmission failed: %v\n", err)
		return fmt.Errorf("failed to send packet: %v", err)
	}

	LogDebug("Packet successfully sent\n")
	return nil
}

// SendPacket sends a single UDP packet with the provided payload.
// The payload parameter is now a []byte, so no conversion is necessary.
func SendPacket(cfg *Config, payload []byte, rateLimit int) error {
	done := make(chan error, 1)
	go func() {
		handle, err := pcap.OpenLive(cfg.Pcap.Iface, cfg.Pcap.SnapLen, cfg.Pcap.Promisc, pcap.BlockForever)
		if err != nil {
			done <- fmt.Errorf("error opening interface: %v", err)
			return
		}
		defer handle.Close()

		if rateLimit > 0 {
			limiter := rate.NewLimiter(rate.Limit(rateLimit), 1)
			if err := limiter.Wait(context.Background()); err != nil {
				done <- fmt.Errorf("rate limiter error: %v", err)
				return
			}
		}
		err = sendSinglePacket(handle, cfg, payload)
		done <- err
	}()
	return <-done
}

// Enhance PayloadNative to better detect incoming Python bytes
func PayloadNative(pyPayload interface{}) [][]byte {
	// Log the actual concrete type for debugging
	LogDebug("PayloadNative called with type %T, concrete type: %v",
		pyPayload, reflect.TypeOf(pyPayload))

	// Add deeper inspection of what's coming from Python
	if strPayload, ok := pyPayload.(string); ok {
		// Python might be serializing the list of bytes as a string
		LogDebug("Received payload as string, length: %d", len(strPayload))
		// If it's a string representation of bytes, convert to a single payload
		return [][]byte{[]byte(strPayload)}
	}

	// Add special case for Python bytearray
	if reflect.TypeOf(pyPayload).Kind() == reflect.Slice {
		// Try to extract raw bytes using reflection
		v := reflect.ValueOf(pyPayload)
		if v.Len() > 0 {
			LogDebug("Trying to extract %d items from slice using reflection", v.Len())

			// Check if it's a slice of slices
			firstItem := v.Index(0).Interface()
			if reflect.TypeOf(firstItem).Kind() == reflect.Slice ||
				reflect.TypeOf(firstItem).Kind() == reflect.String {

				result := make([][]byte, v.Len())
				for i := 0; i < v.Len(); i++ {
					item := v.Index(i).Interface()

					// Try as []byte
					if bytes, ok := item.([]byte); ok {
						result[i] = bytes
					} else if str, ok := item.(string); ok {
						// Try as string
						result[i] = []byte(str)
					} else {
						// Last resort: convert via string representation
						result[i] = []byte(fmt.Sprintf("%v", item))
					}
				}
				LogDebug("Converted %d items using reflection", len(result))
				return result
			}
		}
	}

	// Rest of your existing implementation
	if bytePackets, ok := pyPayload.([]*BytePacket); ok {
		LogDebug("Converting []*BytePacket directly")
		packets := make([][]byte, len(bytePackets))
		for i, bp := range bytePackets {
			if bp != nil {
				packets[i] = bp.Data
			}
		}
		return packets
	}

	// Continue with existing implementation...

	// Your existing switch cases
	// Handle nil case
	if pyPayload == nil {
		return [][]byte{}
	}

	packets := make([][]byte, 0)

	// Handle Python list type conversion
	switch pyList := pyPayload.(type) {
	case []interface{}:
		LogDebug("Converting []interface{} with %d elements", len(pyList))
		for i, item := range pyList {
			switch bytes := item.(type) {
			case []byte:
				// Direct byte slice
				pktCopy := make([]byte, len(bytes))
				copy(pktCopy, bytes)
				packets = append(packets, pktCopy)
			case string:
				// String to byte conversion (sometimes Python bytes come as strings)
				pktCopy := []byte(bytes)
				packets = append(packets, pktCopy)
			default:
				LogWarn("Item %d has unsupported type %T", i, item)
				// Try to handle BytePacket if it's from the Python side
				if reflect.TypeOf(item).String() == "*py_gopacket.BytePacket" {
					if bp, ok := item.(*BytePacket); ok && bp != nil {
						packets = append(packets, bp.Data)
					}
				}
			}
		}
	case [][]byte:
		// Direct Go type
		LogDebug("Already [][]byte, copying directly")
		packets = make([][]byte, len(pyList))
		for i, bytes := range pyList {
			pktCopy := make([]byte, len(bytes))
			copy(pktCopy, bytes)
			packets[i] = pktCopy
		}
	}

	LogDebug("PayloadNative returning %d converted payloads", len(packets))
	return packets
}

// Update SendPackets to use the improved PayloadNative function
func SendPackets(cfg *Config, rawPayloads interface{}, rateLimit int) error {
	LogDebug("SendPackets called with payload type %T", rawPayloads)

	// Convert input to [][]byte regardless of source (Go or Python)
	payloads := PayloadNative(rawPayloads)

	if len(payloads) == 0 {
		LogError("No valid payloads found in input")
		return fmt.Errorf("no valid payloads found in input")
	}

	LogDebug("Successfully converted %d payloads", len(payloads))
	return sendPacketsImpl(cfg, payloads, rateLimit)
}

// SendPacketsNative is a Go-specific function for benchmarking with strongly typed parameters
// This avoids the interface{} overhead and type assertions needed in the Python-compatible version
func sendPacketsNative(cfg *Config, payloads [][]byte, rateLimit int) error {
	LogDebug("SendPacketsNative called with %d payloads", len(payloads))
	return sendPacketsImpl(cfg, payloads, rateLimit)
}

// SendByteArrays accepts a direct [][]byte type (which gopy handles correctly from Python)
// This matches the signature of ResultNative() but for the send direction
func SendByteArrays(cfg *Config, bytePayloads [][]byte, rateLimit int) error {
	LogDebug("SendByteArrays called with %d payloads", len(bytePayloads))
	if len(bytePayloads) == 0 {
		return fmt.Errorf("no payloads provided")
	}

	// Make deep copies of all payloads to ensure memory safety
	safePayloads := make([][]byte, len(bytePayloads))
	for i, pkt := range bytePayloads {
		safePayloads[i] = make([]byte, len(pkt))
		copy(safePayloads[i], pkt)
	}

	// Pass the safely copied payloads to implementation
	return sendPacketsImpl(cfg, safePayloads, rateLimit)
}

// Internal implementation for sending packets
func sendPacketsImpl(cfg *Config, payloads [][]byte, rateLimit int) error {
	// Original SendPackets implementation
	done := make(chan error, 1)
	go func() {
		handle, err := pcap.OpenLive(cfg.Pcap.Iface, cfg.Pcap.SnapLen, cfg.Pcap.Promisc, pcap.BlockForever)
		if err != nil {
			done <- fmt.Errorf("error opening interface: %v", err)
			return
		}
		defer handle.Close()

		var limiter *rate.Limiter
		if rateLimit > 0 {
			limiter = rate.NewLimiter(rate.Limit(rateLimit), 1)
		}

		for _, payload := range payloads {
			if limiter != nil {
				if err := limiter.Wait(context.Background()); err != nil {
					done <- fmt.Errorf("rate limiter error: %v", err)
					return
				}
			}
			if err := sendSinglePacket(handle, cfg, payload); err != nil {
				done <- err
				return
			}
		}
		done <- nil
	}()
	return <-done
}

// PacketSequenceSender is a struct that helps bridge Python byte arrays to Go.
type PacketSequenceSender struct {
	Cfg        *Config
	RateLimit  int
	Payloads   [][]byte
	progressCh chan *PacketSendResult
	isComplete bool
}

// NewPacketSequenceSender creates a sender object that can be populated from Python.
func NewPacketSequenceSender(cfg *Config, rateLimit int) *PacketSequenceSender {
	return &PacketSequenceSender{
		Cfg:        cfg,
		RateLimit:  rateLimit,
		Payloads:   make([][]byte, 0),
		progressCh: make(chan *PacketSendResult, 100), // Buffered channel
		isComplete: false,
	}
}

// AddPayload adds a single payload to the sender.
// This version no longer tries to check or truncate the size—it simply copies the data.
func (bas *PacketSequenceSender) AddPayload(payload []byte) {
	if payload != nil {
		LogDebug("AddPayload received payload of %d bytes", len(payload))
		// Simply make a copy for memory safety and append.
		safeCopy := make([]byte, len(payload))
		copy(safeCopy, payload)
		bas.Payloads = append(bas.Payloads, safeCopy)
	}
}

// Send transmits all the added payloads.
func (bas *PacketSequenceSender) Send() error {
	if len(bas.Payloads) == 0 {
		return fmt.Errorf("no payloads to send")
	}

	LogDebug("PacketSequenceSender.Send() called with %d payloads", len(bas.Payloads))

	// Start goroutine to send packets
	go func() {
		handle, err := pcap.OpenLive(bas.Cfg.Pcap.Iface, bas.Cfg.Pcap.SnapLen, bas.Cfg.Pcap.Promisc, pcap.BlockForever)
		if err != nil {
			bas.progressCh <- &PacketSendResult{
				Index:      0,
				TotalCount: len(bas.Payloads),
				Error:      err,
			}
			close(bas.progressCh)
			bas.isComplete = true
			return
		}
		defer handle.Close()

		var limiter *rate.Limiter
		if bas.RateLimit > 0 {
			limiter = rate.NewLimiter(rate.Limit(bas.RateLimit), 1)
		}

		// Just track start time once
		startTime := time.Now()

		for i, payload := range bas.Payloads {
			// Apply rate limiting if needed
			if limiter != nil {
				if err := limiter.Wait(context.Background()); err != nil {
					bas.progressCh <- &PacketSendResult{
						Index:      i,
						TotalCount: len(bas.Payloads),
						Error:      err,
					}
					continue
				}
			}

			// Send the packet
			err := sendSinglePacket(handle, bas.Cfg, payload)

			// Only report basic progress without precise timing for each packet
			bas.progressCh <- &PacketSendResult{
				Index:      i,
				TotalCount: len(bas.Payloads),
				Error:      err,
			}
		}

		// Calculate total elapsed time at the end
		totalElapsed := time.Since(startTime).Seconds()

		// Send a final result with the total elapsed time
		bas.progressCh <- &PacketSendResult{
			Index:      len(bas.Payloads) - 1,
			TotalCount: len(bas.Payloads),
			Elapsed:    totalElapsed,
			Error:      nil,
		}

		// Signal completion
		close(bas.progressCh)
		bas.isComplete = true
	}()

	return nil
}

// GetNextResult returns the result of the next packet send operation
// Returns nil when all packets have been sent
func (bas *PacketSequenceSender) GetNextResult() *PacketSendResult {
	result, ok := <-bas.progressCh
	if !ok {
		return nil // Channel closed
	}
	return result
}

// IsComplete returns true when all packets have been sent
func (bas *PacketSequenceSender) IsComplete() bool {
	return bas.isComplete
}

// PacketSendResult represents the result of sending a single packet
type PacketSendResult struct {
	Index      int     // Index of the packet in the original payload array
	TotalCount int     // Total number of packets
	Elapsed    float64 // Time elapsed since Send was called (in seconds)
	Error      error   // Error if any
}

// GetError returns error as string or empty string
func (psr *PacketSendResult) GetError() string {
	if psr.Error == nil {
		return ""
	}
	return psr.Error.Error()
}
