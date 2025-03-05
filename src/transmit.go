package ohbother

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

// MultiStreamConfig holds configuration for the multi-stream sender
type MultiStreamConfig struct {
	PacketWorkers  int // Number of workers for packet preparation (default 8)
	StreamCount    int // Number of parallel sending streams (default 4)
	ChannelBuffers int // Size of channel buffers (default 1000)
	ReportInterval int // How often to report progress (packets, default 1000)
}

// MultiStreamSender provides high-performance parallel packet sending while maintaining order
type MultiStreamSender struct {
	Cfg           *Config
	StreamConfig  *MultiStreamConfig
	RateLimit     int
	Payloads      [][]byte
	progressCh    chan *PacketSendResult
	isComplete    bool
	workerDone    chan bool
	schedulerDone chan bool
	cancelCtx     context.Context
	cancelFunc    context.CancelFunc
}

// NewMultiStreamSender creates a high-performance sender with worker pools
func NewMultiStreamSender(cfg *Config, rateLimit int) *MultiStreamSender {
	ctx, cancel := context.WithCancel(context.Background())

	// Default configuration
	streamConfig := &MultiStreamConfig{
		PacketWorkers:  8,
		StreamCount:    4,
		ChannelBuffers: 1000,
		ReportInterval: 1000,
	}

	return &MultiStreamSender{
		Cfg:           cfg,
		RateLimit:     rateLimit,
		StreamConfig:  streamConfig,
		Payloads:      make([][]byte, 0),
		progressCh:    make(chan *PacketSendResult, 100),
		workerDone:    make(chan bool),
		schedulerDone: make(chan bool),
		cancelCtx:     ctx,
		cancelFunc:    cancel,
	}
}

// SetStreamConfig configures the multi-stream sender parameters
func (ms *MultiStreamSender) SetStreamConfig(packetWorkers, streamCount, channelBuffers, reportInterval int) {
	if packetWorkers > 0 {
		ms.StreamConfig.PacketWorkers = packetWorkers
	}
	if streamCount > 0 {
		ms.StreamConfig.StreamCount = streamCount
	}
	if channelBuffers > 0 {
		ms.StreamConfig.ChannelBuffers = channelBuffers
	}
	if reportInterval > 0 {
		ms.StreamConfig.ReportInterval = reportInterval
	}
}

// AddPayload adds a single payload to the sender
func (ms *MultiStreamSender) AddPayload(payload []byte) {
	if payload != nil {
		// Make a copy for memory safety
		safeCopy := make([]byte, len(payload))
		copy(safeCopy, payload)
		ms.Payloads = append(ms.Payloads, safeCopy)
	}
}

// preparedPacket represents a packet ready for transmission
type preparedPacket struct {
	originalIndex int    // Original position in sequence
	packetBytes   []byte // Serialized packet data
	eth           layers.Ethernet
	ip            layers.IPv4
	udp           layers.UDP
	payload       []byte
}

// Send initiates the high-performance transmission process
func (ms *MultiStreamSender) Send() error {
	if len(ms.Payloads) == 0 {
		return fmt.Errorf("no payloads to send")
	}

	totalPackets := len(ms.Payloads)
	LogDebug("MultiStreamSender.Send() called with %d payloads using %d prep workers and %d streams",
		totalPackets, ms.StreamConfig.PacketWorkers, ms.StreamConfig.StreamCount)

	// Create channels for the pipeline
	rawCh := make(chan struct {
		index   int
		payload []byte
	}, ms.StreamConfig.ChannelBuffers)
	prepCh := make(chan *preparedPacket, ms.StreamConfig.ChannelBuffers)
	sendCh := make(chan *preparedPacket, ms.StreamConfig.ChannelBuffers)

	// Start packet preparation workers
	var wg sync.WaitGroup
	for i := 0; i < ms.StreamConfig.PacketWorkers; i++ {
		wg.Add(1)
		go func(workerID int) {
			defer wg.Done()
			ms.preparePackets(rawCh, prepCh)
		}(i)
	}

	// Start scheduler to maintain ordering
	go ms.schedulePackets(prepCh, sendCh, totalPackets)

	// Start sender streams
	handles := make([]*pcap.Handle, ms.StreamConfig.StreamCount)
	var sendWg sync.WaitGroup
	for i := 0; i < ms.StreamConfig.StreamCount; i++ {
		handle, err := pcap.OpenLive(ms.Cfg.Pcap.Iface, ms.Cfg.Pcap.SnapLen, ms.Cfg.Pcap.Promisc, pcap.BlockForever)
		if err != nil {
			ms.cancelFunc() // Cancel everything
			ms.progressCh <- &PacketSendResult{
				Index:      0,
				TotalCount: totalPackets,
				Error:      fmt.Errorf("stream %d: error opening interface: %v", i, err),
			}
			close(ms.progressCh)
			ms.isComplete = true
			return err
		}
		handles[i] = handle

		sendWg.Add(1)
		go func(streamID int, handle *pcap.Handle) {
			defer sendWg.Done()
			ms.sendStream(streamID, handle, sendCh)
		}(i, handle)
	}

	// Feed data into the pipeline
	startTime := time.Now()
	go func() {
		for i, payload := range ms.Payloads {
			select {
			case <-ms.cancelCtx.Done():
				return
			case rawCh <- struct {
				index   int
				payload []byte
			}{i, payload}:
				// Successfully sent to channel
			}
		}
		close(rawCh) // No more data to process
	}()

	// Wait for preparation to complete
	go func() {
		wg.Wait()
		close(prepCh) // No more prepared packets
	}()

	// Wait for scheduler to complete
	go func() {
		<-ms.schedulerDone
		close(sendCh) // No more packets to send
	}()

	// Wait for all sends to complete
	go func() {
		sendWg.Wait()

		// Clean up resources
		for _, handle := range handles {
			handle.Close()
		}

		// Calculate total elapsed time
		totalElapsed := time.Since(startTime).Seconds()

		// Send a final result with the total elapsed time
		ms.progressCh <- &PacketSendResult{
			Index:      totalPackets - 1,
			TotalCount: totalPackets,
			Elapsed:    totalElapsed,
			Error:      nil,
		}

		// Signal completion
		close(ms.progressCh)
		ms.isComplete = true
	}()

	return nil
}

// preparePackets deserializes packets in parallel while preserving order information
func (ms *MultiStreamSender) preparePackets(in <-chan struct {
	index   int
	payload []byte
}, out chan<- *preparedPacket) {
	for item := range in {
		// Check for cancellation
		select {
		case <-ms.cancelCtx.Done():
			return
		default:
			// Continue processing
		}

		// Skip packets that are too small
		minPayloadSize := 18
		if len(item.payload) < minPayloadSize {
			ms.progressCh <- &PacketSendResult{
				Index:      item.index,
				TotalCount: len(ms.Payloads),
				Error: fmt.Errorf("payload size %d is below minimum required size of %d bytes",
					len(item.payload), minPayloadSize),
			}
			continue
		}

		// Prepare layers
		eth := layers.Ethernet{
			SrcMAC:       ms.Cfg.Packet.SrcMAC,
			DstMAC:       ms.Cfg.Packet.DstMAC,
			EthernetType: layers.EthernetTypeIPv4,
		}

		ip := layers.IPv4{
			Version:  4,
			IHL:      5,
			TTL:      64,
			Protocol: layers.IPProtocolUDP,
			SrcIP:    net.ParseIP(ms.Cfg.Packet.SrcIP),
			DstIP:    net.ParseIP(ms.Cfg.Packet.DstIP),
		}

		udp := layers.UDP{
			SrcPort: layers.UDPPort(ms.Cfg.Packet.SrcPort),
			DstPort: layers.UDPPort(ms.Cfg.Packet.DstPort),
		}

		// Compute UDP checksum over the IPv4 pseudo-header
		if err := udp.SetNetworkLayerForChecksum(&ip); err != nil {
			ms.progressCh <- &PacketSendResult{
				Index:      item.index,
				TotalCount: len(ms.Payloads),
				Error:      fmt.Errorf("failed to set network layer for checksum: %v", err),
			}
			continue
		}

		// Serialize the packet
		buffer := gopacket.NewSerializeBuffer()
		opts := gopacket.SerializeOptions{FixLengths: true, ComputeChecksums: true}
		if err := gopacket.SerializeLayers(buffer, opts,
			&eth,
			&ip,
			&udp,
			gopacket.Payload(item.payload),
		); err != nil {
			ms.progressCh <- &PacketSendResult{
				Index:      item.index,
				TotalCount: len(ms.Payloads),
				Error:      fmt.Errorf("failed to serialize packet: %v", err),
			}
			continue
		}

		// Create prepared packet
		packet := &preparedPacket{
			originalIndex: item.index,
			packetBytes:   buffer.Bytes(),
			eth:           eth,
			ip:            ip,
			udp:           udp,
			payload:       item.payload,
		}

		// Send to scheduler
		select {
		case <-ms.cancelCtx.Done():
			return
		case out <- packet:
			// Successfully sent
		}
	}
}

// schedulePackets ensures packets are sent in the correct order
func (ms *MultiStreamSender) schedulePackets(in <-chan *preparedPacket, out chan<- *preparedPacket, total int) {
	defer close(ms.schedulerDone)

	// Use priority queue to ensure ordering
	pending := make(map[int]*preparedPacket)
	nextIndex := 0

	for packet := range in {
		// Check for cancellation
		select {
		case <-ms.cancelCtx.Done():
			return
		default:
			// Continue processing
		}

		// Store the packet
		pending[packet.originalIndex] = packet

		// Send packets in order when possible
		for {
			packet, exists := pending[nextIndex]
			if !exists {
				break // Wait for the next packet in sequence
			}

			select {
			case <-ms.cancelCtx.Done():
				return
			case out <- packet:
				// Packet sent, remove from pending and advance
				delete(pending, nextIndex)
				nextIndex++
			}
		}

		// Report progress occasionally
		if nextIndex > 0 && nextIndex%ms.StreamConfig.ReportInterval == 0 {
			ms.progressCh <- &PacketSendResult{
				Index:      nextIndex - 1,
				TotalCount: total,
				Error:      nil,
			}
		}
	}

	// Process any remaining packets in order
	for nextIndex < total {
		packet, exists := pending[nextIndex]
		if !exists {
			// This shouldn't happen if all packets were processed
			break
		}

		select {
		case <-ms.cancelCtx.Done():
			return
		case out <- packet:
			delete(pending, nextIndex)
			nextIndex++
		}
	}
}

// sendStream handles sending packets from a single stream
func (ms *MultiStreamSender) sendStream(streamID int, handle *pcap.Handle, in <-chan *preparedPacket) {
	var limiter *rate.Limiter
	if ms.RateLimit > 0 {
		// Each stream gets its proportional share of the total rate
		streamRate := ms.RateLimit / ms.StreamConfig.StreamCount
		if streamRate < 1 {
			streamRate = 1
		}
		limiter = rate.NewLimiter(rate.Limit(streamRate), 1)
	}

	for packet := range in {
		// Check for cancellation
		select {
		case <-ms.cancelCtx.Done():
			return
		default:
			// Continue processing
		}

		// Apply rate limiting if needed
		if limiter != nil {
			if err := limiter.Wait(ms.cancelCtx); err != nil {
				if err != context.Canceled {
					ms.progressCh <- &PacketSendResult{
						Index:      packet.originalIndex,
						TotalCount: len(ms.Payloads),
						Error:      fmt.Errorf("stream %d: rate limiter error: %v", streamID, err),
					}
				}
				continue
			}
		}

		// Send the packet
		if err := handle.WritePacketData(packet.packetBytes); err != nil {
			ms.progressCh <- &PacketSendResult{
				Index:      packet.originalIndex,
				TotalCount: len(ms.Payloads),
				Error:      fmt.Errorf("stream %d: failed to send packet: %v", streamID, err),
			}
			continue
		}
	}
}

// GetNextResult returns the result of the next packet send operation
func (ms *MultiStreamSender) GetNextResult() *PacketSendResult {
	result, ok := <-ms.progressCh
	if !ok {
		return nil // Channel closed
	}
	return result
}

// IsComplete returns true when all packets have been sent
func (ms *MultiStreamSender) IsComplete() bool {
	return ms.isComplete
}

// Cancel stops all sending operations
func (ms *MultiStreamSender) Cancel() {
	ms.cancelFunc()
}
