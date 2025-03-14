package transmit

import (
	"context"
	"fmt"
	"net"
	"reflect"
	"sync"
	"time"

	"github.com/gopacket/gopacket"
	"github.com/gopacket/gopacket/layers"
	"github.com/gopacket/gopacket/pcap"
	"golang.org/x/time/rate"

	"ohbother/src/config"
	"ohbother/src/receive"
)

type Config = config.Config
type BytePacket = receive.BytePacket

var LogDebug = config.LogDebug
var LogInfo = config.LogInfo
var LogWarn = config.LogWarn
var LogError = config.LogError

// Pool of reusable serialize buffers to reduce GC pressure
var serializeBufferPool = sync.Pool{
	New: func() interface{} {
		return gopacket.NewSerializeBuffer()
	},
}

// sendSinglePacket transmits a single UDP packet with the given payload
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

	// Get buffer from pool
	buffer := serializeBufferPool.Get().(gopacket.SerializeBuffer)
	buffer.Clear()
	opts := gopacket.SerializeOptions{FixLengths: true, ComputeChecksums: true}

	if err := gopacket.SerializeLayers(buffer, opts,
		&eth,
		&ip,
		&udp,
		gopacket.Payload(payload),
	); err != nil {
		LogError("Packet serialization failed: %v\n", err)
		serializeBufferPool.Put(buffer)
		return fmt.Errorf("failed to serialize packet: %v", err)
	}

	// Copy the bytes immediately into our own slice
	serializedData := make([]byte, len(buffer.Bytes()))
	copy(serializedData, buffer.Bytes())

	// Then use our safe copy for the rest of the function
	packetBytes := serializedData
	LogDebug("  - Total packet size: %d bytes\n", len(packetBytes))
	LogDebug("  - Handle link type: %v\n", handle.LinkType())

	if err := handle.WritePacketData(packetBytes); err != nil {
		LogError("Packet transmission failed: %v\n", err)
		serializeBufferPool.Put(buffer)
		return fmt.Errorf("failed to send packet: %v", err)
	}

	serializeBufferPool.Put(buffer)
	LogDebug("Packet successfully sent\n")
	return nil
}

// SendPacket transmits a single UDP packet
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

// PayloadNative converts various payload formats to [][]byte
func PayloadNative(pyPayload interface{}) [][]byte {
	LogDebug("PayloadNative called with type %T, concrete type: %v",
		pyPayload, reflect.TypeOf(pyPayload))

	// Handle Python string type
	if strPayload, ok := pyPayload.(string); ok {
		LogDebug("Received payload as string, length: %d", len(strPayload))
		return [][]byte{[]byte(strPayload)}
	}

	// Handle Python slices via reflection
	if reflect.TypeOf(pyPayload).Kind() == reflect.Slice {
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

	// Handle BytePacket type directly
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

	// Handle nil case
	if pyPayload == nil {
		return [][]byte{}
	}

	packets := make([][]byte, 0)

	// Handle standard type conversions
	switch pyList := pyPayload.(type) {
	case []interface{}:
		LogDebug("Converting []interface{} with %d elements", len(pyList))
		packets = make([][]byte, 0, len(pyList))
		for i, item := range pyList {
			switch bytes := item.(type) {
			case []byte:
				pktCopy := make([]byte, len(bytes))
				copy(pktCopy, bytes)
				packets = append(packets, pktCopy)
			case string:
				packets = append(packets, []byte(bytes))
			default:
				LogWarn("Item %d has unsupported type %T", i, item)
				if reflect.TypeOf(item).String() == "*py_gopacket.BytePacket" {
					if bp, ok := item.(*BytePacket); ok && bp != nil {
						packets = append(packets, bp.Data)
					}
				}
			}
		}
	case [][]byte:
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

// SendPackets transmits multiple packets with optional rate limiting
func SendPackets(cfg *Config, rawPayloads interface{}, rateLimit int) error {
	LogDebug("SendPackets called with payload type %T", rawPayloads)

	payloads := PayloadNative(rawPayloads)
	if len(payloads) == 0 {
		LogError("No valid payloads found in input")
		return fmt.Errorf("no valid payloads found in input")
	}

	LogDebug("Successfully converted %d payloads", len(payloads))
	return sendPacketsImpl(cfg, payloads, rateLimit)
}

// SendPacketsNative is a Go-specific function for direct typed parameters
func SendPacketsNative(cfg *Config, payloads [][]byte, rateLimit int) error {
	LogDebug("SendPacketsNative called with %d payloads", len(payloads))
	return sendPacketsImpl(cfg, payloads, rateLimit)
}

// SendByteArrays accepts a direct [][]byte type for Python integration
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

	return sendPacketsImpl(cfg, safePayloads, rateLimit)
}

// Internal implementation for sending packets
func sendPacketsImpl(cfg *Config, payloads [][]byte, rateLimit int) error {
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

// PacketSequenceSender provides a simple API for packet transmission
type PacketSequenceSender struct {
	Cfg        *Config
	RateLimit  int
	Payloads   [][]byte
	progressCh chan *PacketSendResult
	isComplete bool
}

// NewPacketSequenceSender creates a sender with specified configuration
func NewPacketSequenceSender(cfg *Config, rateLimit int) *PacketSequenceSender {
	return &PacketSequenceSender{
		Cfg:        cfg,
		RateLimit:  rateLimit,
		Payloads:   make([][]byte, 0),
		progressCh: make(chan *PacketSendResult, 100),
		isComplete: false,
	}
}

// AddPayload adds a payload to the sender's queue
func (bas *PacketSequenceSender) AddPayload(payload []byte) {
	if payload != nil {
		LogDebug("AddPayload received payload of %d bytes", len(payload))
		safeCopy := make([]byte, len(payload))
		copy(safeCopy, payload)
		bas.Payloads = append(bas.Payloads, safeCopy)
	}
}

// Send initiates transmission of all queued payloads
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

			// Report progress
			bas.progressCh <- &PacketSendResult{
				Index:      i,
				TotalCount: len(bas.Payloads),
				Error:      err,
			}
		}

		// Calculate total elapsed time at the end
		totalElapsed := time.Since(startTime).Seconds()

		// Send a final result with the total elapsed time
		select {
		case bas.progressCh <- &PacketSendResult{
			Index:      len(bas.Payloads) - 1,
			TotalCount: len(bas.Payloads),
			Elapsed:    totalElapsed,
			Error:      nil,
		}:
		default:
			// If channel is full, skip sending the final result.
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

// GetError returns error as string or empty string
func (psr *PacketSendResult) GetError() string {
	if psr.Error == nil {
		return ""
	}
	return psr.Error.Error()
}
