package ohbother

import (
	"context"
	"fmt"
	"net"
	"reflect"
	"sync"
	"sync/atomic"
	"time"

	"runtime"

	"github.com/gopacket/gopacket"
	"github.com/gopacket/gopacket/layers"
	"github.com/gopacket/gopacket/pcap"
	"golang.org/x/time/rate"
)

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

	packetBytes := buffer.Bytes()
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
func sendPacketsNative(cfg *Config, payloads [][]byte, rateLimit int) error {
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
	PacketWorkers    int  // Number of workers for packet preparation
	StreamCount      int  // Number of parallel sending streams
	ChannelBuffers   int  // Size of channel buffers
	ReportInterval   int  // How often to report progress (packets)
	EnableCPUPinning bool // Whether to pin threads to CPU cores
	DisableOrdering  bool // Enable raw throughput mode with no ordering
	TurnstileBurst   int  // How many packets can be sent in a burst
	EnableMetrics    bool // Enable lightweight performance metrics
}

// MultiStreamSender provides high-performance parallel packet sending
type MultiStreamSender struct {
	Cfg            *Config
	StreamConfig   *MultiStreamConfig
	RateLimit      int
	Payloads       [][]byte
	progressCh     chan *PacketSendResult
	progressBuffer []*PacketSendResult // Buffer to store recent results
	maxBufferSize  int                 // Maximum buffer size
	isComplete     atomic.Bool         // Atomic flag: send complete
	workerDone     chan bool
	schedulerDone  chan bool
	cancelCtx      context.Context
	cancelFunc     context.CancelFunc
	nextToSend     atomic.Uint64  // Atomic counter for turnstile
	turnstileCh    chan struct{}  // Channel-based turnstile for rate limiting
	metrics        *senderMetrics // Lightweight metrics
	channelClosed  atomic.Bool    // Atomic flag: progressCh closed
	mutex          sync.Mutex
	started        atomic.Bool // New flag: transmission started?
}

// NewMultiStreamSender creates a high-performance sender with worker pools
func NewMultiStreamSender(cfg *Config, rateLimit int) *MultiStreamSender {
	ctx, cancel := context.WithCancel(context.Background())

	// Default configuration with all fields initialized
	streamConfig := &MultiStreamConfig{
		PacketWorkers:    8,
		StreamCount:      4,
		ChannelBuffers:   1000,
		ReportInterval:   1000,
		EnableCPUPinning: false, // Default to false for wider compatibility
		DisableOrdering:  false, // Default to ordered transmission
		TurnstileBurst:   1,     // Default to single packet burst
		EnableMetrics:    true,  // Default to metrics enabled
	}

	return &MultiStreamSender{
		Cfg:            cfg,
		RateLimit:      rateLimit,
		StreamConfig:   streamConfig,
		Payloads:       make([][]byte, 0),
		progressCh:     make(chan *PacketSendResult, 1000),
		progressBuffer: make([]*PacketSendResult, 0, 1000),
		maxBufferSize:  1000,
		workerDone:     make(chan bool),
		schedulerDone:  make(chan bool),
		cancelCtx:      ctx,
		cancelFunc:     cancel,
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

	// Log the configuration for debugging
	LogDebug("MultiStreamSender configured with: workers=%d, streams=%d, buffers=%d, report=%d",
		ms.StreamConfig.PacketWorkers,
		ms.StreamConfig.StreamCount,
		ms.StreamConfig.ChannelBuffers,
		ms.StreamConfig.ReportInterval)
}

// SetAdvancedConfig configures the advanced streaming options
func (ms *MultiStreamSender) SetAdvancedConfig(enableCPUPinning bool, disableOrdering bool,
	turnstileBurst int, enableMetrics bool) {
	ms.StreamConfig.EnableCPUPinning = enableCPUPinning
	ms.StreamConfig.DisableOrdering = disableOrdering

	if turnstileBurst > 0 {
		ms.StreamConfig.TurnstileBurst = turnstileBurst
	}

	ms.StreamConfig.EnableMetrics = enableMetrics
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

// Send initiates high-performance parallel packet transmission
func (ms *MultiStreamSender) Send() error {
	// Prevent multiple invocations.
	if ms.started.Load() {
		return nil
	}
	ms.started.Store(true)

	// Initialize metrics
	ms.metrics = &senderMetrics{}

	// Initialize the atomic counter for ordering - ADD THIS LINE
	ms.nextToSend.Store(0)

	// Set up channels with specified buffer sizes
	rawCh := make(chan struct {
		index   int
		payload []byte
	}, ms.StreamConfig.ChannelBuffers)
	prepCh := make(chan *preparedPacket, ms.StreamConfig.ChannelBuffers)

	// Create turnstile with appropriate burst size
	burstSize := max(1, ms.StreamConfig.TurnstileBurst)
	ms.turnstileCh = make(chan struct{}, burstSize)

	// Set up rate limiting goroutine if needed
	if ms.RateLimit > 0 {
		go ms.rateLimitTurnstile()
	} else {
		// No rate limit - fill turnstile for maximum throughput
		go func() {
			for {
				select {
				case <-ms.cancelCtx.Done():
					return
				case ms.turnstileCh <- struct{}{}:
					// Keep filling
				default:
					// Briefly wait if full
					time.Sleep(time.Microsecond)
				}
			}
		}()
	}

	// Start preparation workers
	var wg sync.WaitGroup
	for i := 0; i < ms.StreamConfig.PacketWorkers; i++ {
		wg.Add(1)
		go func(workerID int) {
			defer wg.Done()
			ms.preparePackets(rawCh, prepCh)
		}(i)
	}

	// Start sender streams with modified approach
	handles := make([]*pcap.Handle, ms.StreamConfig.StreamCount)
	var sendWg sync.WaitGroup

	// Open all handles first
	for i := 0; i < ms.StreamConfig.StreamCount; i++ {
		handle, err := pcap.OpenLive(ms.Cfg.Pcap.Iface, ms.Cfg.Pcap.SnapLen,
			ms.Cfg.Pcap.Promisc, pcap.BlockForever)
		if err != nil {
			// Error handling
			ms.cancelFunc()
			return fmt.Errorf("failed to open interface for stream %d: %v", i, err)
		}
		handles[i] = handle

		// Start sender goroutine immediately
		sendWg.Add(1)
		go func(streamID int, handle *pcap.Handle) {
			defer sendWg.Done()
			ms.sendPackets(streamID, handle, prepCh)
		}(i, handle)
	}

	// Start feeding data immediately
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

		// Wait for all preparations to complete
		wg.Wait()
		// Signal end of stream to senders
		close(prepCh)
	}()

	// Wait for completion
	go func() {
		// Wait for all senders to complete
		sendWg.Wait()

		// Clean up resources
		for _, handle := range handles {
			handle.Close()
		}

		// Calculate total elapsed time
		totalElapsed := time.Since(startTime).Seconds()

		// LOCK to protect channel operations
		ms.mutex.Lock()
		defer ms.mutex.Unlock()

		// Only proceed if channel isn't already closed
		if !ms.channelClosed.Load() {
			// Send a final result with the total elapsed time
			select {
			case ms.progressCh <- &PacketSendResult{
				Index:      len(ms.Payloads) - 1,
				TotalCount: len(ms.Payloads),
				Elapsed:    totalElapsed,
				Error:      nil,
			}:
			default:
				// If channel is full, skip sending the final result.
			}

			// Close the channel and mark as closed
			close(ms.progressCh)
			ms.channelClosed.Store(true)
			ms.isComplete.Store(true)
		}
	}()

	return nil
}

// sendPackets transmits packets from a specific stream
func (ms *MultiStreamSender) sendPackets(streamID int, handle *pcap.Handle, in <-chan *preparedPacket) {
	// Pin to CPU if enabled
	if ms.StreamConfig.EnableCPUPinning {
		cpuID := 1 + streamID // Skip CPU 0
		if err := pinToCPU(cpuID); err != nil {
			ms.progressCh <- &PacketSendResult{
				Error: fmt.Errorf("stream %d: failed to pin to CPU %d: %v", streamID, cpuID, err),
			}
		}
	}

	for packet := range in {
		// Check cancellation
		select {
		case <-ms.cancelCtx.Done():
			return
		default:
			// Continue
		}

		var startWait time.Time
		if ms.StreamConfig.EnableMetrics {
			startWait = time.Now()
		}

		// Get rate limiting token first
		<-ms.turnstileCh

		// Then wait for ordering turn
		if !ms.StreamConfig.DisableOrdering {
			expectedSeq := uint64(packet.originalIndex)
			for ms.nextToSend.Load() != expectedSeq {
				// Brief pause to reduce CPU usage during spin wait
				runtime.Gosched()
				//time.Sleep(50 * time.Microsecond)
			}
		}

		if ms.StreamConfig.EnableMetrics && !ms.StreamConfig.DisableOrdering {
			waitNs := time.Since(startWait).Nanoseconds()
			ms.metrics.waitTime.Add(uint64(waitNs))
		}

		var startSend time.Time
		if ms.StreamConfig.EnableMetrics {
			startSend = time.Now()
		}

		// Send the packet
		if err := handle.WritePacketData(packet.packetBytes); err != nil {
			select {
			case ms.progressCh <- &PacketSendResult{
				Index:      packet.originalIndex,
				TotalCount: len(ms.Payloads),
				Error:      fmt.Errorf("stream %d: failed to send packet: %v", streamID, err),
			}:
			default:
				// If full, drop the error to avoid blocking.
			}
			ms.metrics.packetsDropped.Add(1)
			continue
		}

		if !ms.StreamConfig.DisableOrdering {
			// Advance the turnstile for the next packet
			ms.nextToSend.Add(1)
		}

		if ms.StreamConfig.EnableMetrics {
			sendNs := time.Since(startSend).Nanoseconds()
			ms.metrics.sendTime.Add(uint64(sendNs))
			ms.metrics.packetsProcessed.Add(1)
		}
	}
}

// rateLimitTurnstile controls the rate of packet transmission
func (ms *MultiStreamSender) rateLimitTurnstile() {
	// Calculate interval between packets
	interval := time.Second / time.Duration(ms.RateLimit)
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ms.cancelCtx.Done():
			return
		case <-ticker.C:
			// Add token to turnstile
			select {
			case ms.turnstileCh <- struct{}{}:
				// Token added
			default:
				// Channel full, skip this token
			}
		}
	}
}

// GetMetrics returns performance metrics for the sender
func (ms *MultiStreamSender) GetMetrics() map[string]uint64 {
	if !ms.StreamConfig.EnableMetrics || ms.metrics == nil {
		return nil
	}

	return map[string]uint64{
		"packets_processed": ms.metrics.packetsProcessed.Load(),
		"packets_dropped":   ms.metrics.packetsDropped.Load(),
		"prepare_time_ns":   ms.metrics.prepareTime.Load(),
		"wait_time_ns":      ms.metrics.waitTime.Load(),
		"send_time_ns":      ms.metrics.sendTime.Load(),
		"avg_prepare_ns":    safeDivide(ms.metrics.prepareTime.Load(), ms.metrics.packetsProcessed.Load()),
		"avg_wait_ns":       safeDivide(ms.metrics.waitTime.Load(), ms.metrics.packetsProcessed.Load()),
		"avg_send_ns":       safeDivide(ms.metrics.sendTime.Load(), ms.metrics.packetsProcessed.Load()),
	}
}

// safeDivide performs division with a zero check
func safeDivide(a, b uint64) uint64 {
	if b == 0 {
		return 0
	}
	return a / b
}

// senderMetrics stores performance metrics
type senderMetrics struct {
	prepareTime      atomic.Uint64 // Total nanoseconds spent preparing packets
	waitTime         atomic.Uint64 // Total nanoseconds spent waiting at turnstile
	sendTime         atomic.Uint64 // Total nanoseconds spent sending packets
	packetsProcessed atomic.Uint64 // Total packets processed
	packetsDropped   atomic.Uint64 // Packets dropped due to errors
}

// preparePackets deserializes packets in parallel
func (ms *MultiStreamSender) preparePackets(in <-chan struct {
	index   int
	payload []byte
}, out chan<- *preparedPacket) {
	// Initialize header template
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

	// Set up UDP checksum - do this once
	udp.SetNetworkLayerForChecksum(&ip)

	for item := range in {
		var startPrepare time.Time
		if ms.StreamConfig.EnableMetrics {
			startPrepare = time.Now()
		}

		// Create a new packet from the template
		packet := &preparedPacket{
			originalIndex: item.index,
			eth:           eth,
			ip:            ip,
			udp:           udp,
			payload:       item.payload,
		}

		// Serialize the packet
		buffer := serializeBufferPool.Get().(gopacket.SerializeBuffer)
		buffer.Clear()

		opts := gopacket.SerializeOptions{
			FixLengths:       true,
			ComputeChecksums: true,
		}

		err := gopacket.SerializeLayers(buffer, opts,
			&packet.eth,
			&packet.ip,
			&packet.udp,
			gopacket.Payload(packet.payload),
		)

		if err != nil {
			serializeBufferPool.Put(buffer)
			select {
			case ms.progressCh <- &PacketSendResult{
				Index:      item.index,
				TotalCount: len(ms.Payloads),
				Error:      fmt.Errorf("failed to serialize packet: %v", err),
			}:
			default:
				// Drop error if progressCh is full.
			}
			continue
		}

		// Store serialized data
		packet.packetBytes = make([]byte, len(buffer.Bytes()))
		copy(packet.packetBytes, buffer.Bytes())

		serializeBufferPool.Put(buffer)

		if ms.StreamConfig.EnableMetrics {
			prepNs := time.Since(startPrepare).Nanoseconds()
			ms.metrics.prepareTime.Add(uint64(prepNs))
		}

		// Send to output channel
		select {
		case <-ms.cancelCtx.Done():
			return
		case out <- packet:
			// Successfully sent to channel
		}
	}
}

// IsComplete returns true when all packets have been sent
func (ms *MultiStreamSender) IsComplete() bool {
	return ms.isComplete.Load()
}

// GetNextResult returns the next result with smart buffering
func (ms *MultiStreamSender) GetNextResult() *PacketSendResult {
	ms.mutex.Lock()
	defer ms.mutex.Unlock()

	// If we have buffered results, return one
	if len(ms.progressBuffer) > 0 {
		result := ms.progressBuffer[0]
		ms.progressBuffer = ms.progressBuffer[1:]
		return result
	}

	// Check if no more results are expected
	if ms.isComplete.Load() && ms.channelClosed.Load() {
		return nil
	}

	// Try to get multiple results at once to prevent blocking
	// This helps decouple Go and Python speeds
	resultCount := 0
	for resultCount < 100 { // Get up to 100 at a time
		select {
		case result, ok := <-ms.progressCh:
			if !ok {
				ms.channelClosed.Store(true)
				if len(ms.progressBuffer) > 0 {
					result := ms.progressBuffer[0]
					ms.progressBuffer = ms.progressBuffer[1:]
					return result
				}
				return nil
			}

			// Store result in buffer
			ms.progressBuffer = append(ms.progressBuffer, result)
			resultCount++

		default:
			// No more results available right now
			break
		}
	}

	// If we got any results, return the first one
	if len(ms.progressBuffer) > 0 {
		result := ms.progressBuffer[0]
		ms.progressBuffer = ms.progressBuffer[1:]
		return result
	}

	return nil
}

// Wait blocks until all packets have been sent
func (ms *MultiStreamSender) Wait() {
	for !ms.isComplete.Load() {
		time.Sleep(10 * time.Millisecond)
	}
}

// GetSentCount returns the number of packets that were successfully sent
func (ms *MultiStreamSender) GetSentCount() int {
	if ms.metrics != nil {
		return int(ms.metrics.packetsProcessed.Load())
	}
	return 0
}

// GetErrorCount returns the number of packets that encountered errors
func (ms *MultiStreamSender) GetErrorCount() int {
	if ms.metrics != nil {
		return int(ms.metrics.packetsDropped.Load())
	}
	return 0
}

// GetStreamConfig returns the current streaming configuration
func (ms *MultiStreamSender) GetStreamConfig() *MultiStreamConfig {
	return ms.StreamConfig
}

// IsOrderingEnabled returns whether packet ordering is enabled
func (ms *MultiStreamSender) IsOrderingEnabled() bool {
	return !ms.StreamConfig.DisableOrdering
}

// IsCPUPinningEnabled returns whether CPU pinning is enabled
func (ms *MultiStreamSender) IsCPUPinningEnabled() bool {
	return ms.StreamConfig.EnableCPUPinning
}

// GetTurnstileBurst returns the configured burst size
func (ms *MultiStreamSender) GetTurnstileBurst() int {
	return ms.StreamConfig.TurnstileBurst
}

// AreMetricsEnabled returns whether metrics collection is enabled
func (ms *MultiStreamSender) AreMetricsEnabled() bool {
	return ms.StreamConfig.EnableMetrics
}

// FastConvertPayloads converts multiple byte arrays in parallel
func (ms *MultiStreamSender) FastConvertPayloads(payloads [][]byte) [][]byte {
	// Get the Python list size
	size := len(payloads)
	if size <= 0 {
		return nil
	}

	// Determine worker count for maximum CPU usage
	numWorkers := runtime.NumCPU() * 4
	if size < numWorkers {
		numWorkers = size
	}

	// Create result array
	results := make([][]byte, size)

	// Use a wait group to synchronize workers
	var wg sync.WaitGroup

	// Process in batches using goroutines - calculate chunk sizes more efficiently
	batchSize := (size + numWorkers - 1) / numWorkers

	// Pre-allocate batch boundaries for better work distribution
	batches := make([]struct{ start, end int }, numWorkers)
	pos := 0
	for i := 0; i < numWorkers; i++ {
		batches[i].start = pos
		batchItems := batchSize
		if i < size%numWorkers {
			batchItems++ // Distribute remainder evenly
		}
		pos += batchItems
		batches[i].end = pos
		if pos >= size {
			break
		}
	}

	for w := 0; w < numWorkers; w++ {
		batch := batches[w]
		if batch.start >= size {
			continue
		}

		wg.Add(1)

		go func(startIdx, endIdx int) {
			defer wg.Done()

			// Each worker processes its own chunk with better locality
			localResults := make([][]byte, endIdx-startIdx)

			for i := startIdx; i < endIdx; i++ {
				payload := payloads[i]
				if payload != nil {
					// Deep copy for memory safety
					data := make([]byte, len(payload))
					copy(data, payload)
					localResults[i-startIdx] = data
				}
			}

			// Efficiently copy results back with one lock operation
			for i := startIdx; i < endIdx; i++ {
				results[i] = localResults[i-startIdx]
			}
		}(batch.start, batch.end)
	}

	// Wait for all goroutines to complete
	wg.Wait()

	return results
}

// AddPayloadsFlat adds multiple payloads from a flattened representation
// Exported to Python - uses compatible types ([]byte and []int)
func (ms *MultiStreamSender) AddPayloadsFlat(flatData []byte, offsets []int) int {
	// Reconstruct the byte slices using optimized function
	payloads := ReconstructByteArrays(flatData, offsets)
	count := len(payloads)

	// For small payload counts, add sequentially to avoid goroutine overhead
	if count < 100 {
		for _, payload := range payloads {
			ms.AddPayload(payload)
		}

		LogDebug("Added %d payloads from flattened data (%d bytes, %d offsets)\n",
			count, len(flatData), len(offsets))

		return count
	}

	// For larger payload sets, use parallel processing
	var wg sync.WaitGroup

	// Calculate optimal worker count
	numWorkers := runtime.NumCPU()
	if numWorkers > 8 {
		numWorkers = 8
	}

	// Ensure we don't create more workers than needed
	if numWorkers > count {
		numWorkers = count
	}

	// Calculate items per worker
	itemsPerWorker := (count + numWorkers - 1) / numWorkers

	for w := 0; w < numWorkers; w++ {
		wg.Add(1)

		startIdx := w * itemsPerWorker
		endIdx := startIdx + itemsPerWorker
		if endIdx > count {
			endIdx = count
		}

		go func(start, end int) {
			defer wg.Done()

			// Process a batch of payloads
			for i := start; i < end; i++ {
				if payloads[i] != nil {
					// Make a copy for memory safety
					// (AddPayload already makes a copy, but we ensure consistency)
					ms.AddPayload(payloads[i])
				}
			}
		}(startIdx, endIdx)
	}

	wg.Wait()

	LogDebug("Added %d payloads from flattened data (%d bytes, %d offsets) using %d workers\n",
		count, len(flatData), len(offsets), numWorkers)

	return count
}
