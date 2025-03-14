package ohbother

import (
	"context"
	"fmt"
	"net"
	"runtime"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gopacket/gopacket"
	"github.com/gopacket/gopacket/layers"
	"github.com/gopacket/gopacket/pcap"
)

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
	started        atomic.Bool            // New flag: transmission started?
	errorCh        chan *PacketSendResult // Dedicated channel for error reports
	closeOnce      sync.Once              // Ensures progressCh is closed only once
	payloadMutex   sync.Mutex             // New mutex to protect Payloads
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

	ms := &MultiStreamSender{
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
		errorCh:        make(chan *PacketSendResult, 1000), // Will try 30M if sigsev
	}

	// Start error handling goroutine
	go func() {
		for errResult := range ms.errorCh {
			// Lock to ensure thread-safe access to progressCh
			ms.mutex.Lock()
			if !ms.channelClosed.Load() {
				// Non-blocking send to progressCh
				select {
				case ms.progressCh <- errResult:
					// Successfully sent
				default:
					// Channel full, drop the error
					if ms.metrics != nil {
						ms.metrics.packetsDropped.Add(1)
					}
				}
			}
			ms.mutex.Unlock()
		}
	}()

	return ms
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

		ms.payloadMutex.Lock()
		ms.Payloads = append(ms.Payloads, safeCopy)
		ms.payloadMutex.Unlock()
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
		if err := PinToCPU(cpuID); err != nil {
			ms.reportError(-1, fmt.Errorf("stream %d: failed to pin to CPU %d: %v", streamID, cpuID, err))
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

		// CRITICAL FIX: Safely check packet and packet.packetBytes before using
		if packet == nil {
			ms.reportError(-1, fmt.Errorf("stream %d: received nil packet", streamID))
			// Still advance the counter to prevent deadlock
			if !ms.StreamConfig.DisableOrdering {
				ms.nextToSend.Add(1)
			}
			continue
		}

		if packet.packetBytes == nil || len(packet.packetBytes) == 0 {
			ms.reportError(packet.originalIndex, fmt.Errorf("stream %d: nil or empty packet bytes", streamID))
			ms.metrics.packetsDropped.Add(1)

			// Still advance the counter to prevent deadlock
			if !ms.StreamConfig.DisableOrdering {
				ms.nextToSend.Add(1)
			}
			continue
		}

		// CRITICAL FIX: Try-catch equivalent for WritePacketData to prevent SIGSEGV
		var sendErr error
		func() {
			defer func() {
				if r := recover(); r != nil {
					sendErr = fmt.Errorf("panic in WritePacketData: %v", r)
				}
			}()

			sendErr = handle.WritePacketData(packet.packetBytes)
		}()

		if sendErr != nil {
			// Use reportError instead of direct channel write
			ms.reportError(packet.originalIndex, fmt.Errorf("stream %d: failed to send packet: %v", streamID, sendErr))
			ms.metrics.packetsDropped.Add(1)
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
	// Initialize header template once per worker
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

	// Reusable serialization options
	opts := gopacket.SerializeOptions{
		FixLengths:       true,
		ComputeChecksums: true,
	}

	// Define maximum safe payload size (typical MTU minus headers)
	const maxSafePayloadSize = 1472 // 1500 (MTU) - 20 (IP) - 8 (UDP)

	for item := range in {
		var startPrepare time.Time
		if ms.StreamConfig.EnableMetrics {
			startPrepare = time.Now()
		}

		// Get a fresh buffer for this iteration
		buffer := serializeBufferPool.Get().(gopacket.SerializeBuffer)
		buffer.Clear()

		// Thorough payload validation - prevent nil pointer derefs and overlarge packets
		if item.payload == nil {
			ms.reportError(item.index, fmt.Errorf("invalid nil payload"))
			serializeBufferPool.Put(buffer)
			continue
		}

		payloadLen := len(item.payload)
		if payloadLen < 1 {
			ms.reportError(item.index, fmt.Errorf("payload too small: %d bytes", payloadLen))
			serializeBufferPool.Put(buffer)
			continue
		}

		if payloadLen > maxSafePayloadSize {
			ms.reportError(item.index, fmt.Errorf("payload too large: %d bytes (max %d)", payloadLen, maxSafePayloadSize))
			serializeBufferPool.Put(buffer)
			continue
		}

		// Calculate exact buffer size needed - headers plus payload
		estimatedSize := 42 + payloadLen // Ethernet (14) + IPv4 (20) + UDP (8) + payload

		// Safely prepare buffer for serialization
		var allocationErr error
		func() {
			defer func() {
				if r := recover(); r != nil {
					allocationErr = fmt.Errorf("buffer allocation failed: %v", r)
				}
			}()
			// This can panic if memory allocation fails
			buffer.PrependBytes(estimatedSize)
		}()
		if allocationErr != nil {
			ms.reportError(item.index, allocationErr)
			serializeBufferPool.Put(buffer)
			continue
		}

		// Check if PrependBytes succeeded
		if buffer.Bytes() == nil {
			ms.reportError(item.index, fmt.Errorf("failed to allocate packet buffer"))
			serializeBufferPool.Put(buffer)
			continue
		}

		// Create a new packet but defer payload copying until after validation
		packet := &preparedPacket{
			originalIndex: item.index,
			eth:           eth,
			ip:            ip,
			udp:           udp,
		}

		// Copy payload with additional safety checks
		if item.payload != nil && len(item.payload) > 0 {
			// Allocate and copy in one atomic operation with bounds checking
			packet.payload = append([]byte(nil), item.payload...)
		} else {
			packet.payload = []byte{} // Empty but non-nil payload
		}

		// Safe serialization with panic recovery
		var err error
		func() {
			defer func() {
				if r := recover(); r != nil {
					err = fmt.Errorf("serialization panic: %v", r)
				}
			}()
			err = gopacket.SerializeLayers(buffer, opts,
				&packet.eth,
				&packet.ip,
				&packet.udp,
				gopacket.Payload(packet.payload),
			)
		}()
		if err != nil {
			ms.reportError(item.index, fmt.Errorf("failed to serialize packet: %v", err))
			serializeBufferPool.Put(buffer)
			continue
		}

		// Copy serialized data with bounds checking
		serializedData := buffer.Bytes()
		if serializedData == nil {
			ms.reportError(item.index, fmt.Errorf("serialization produced nil buffer"))
			serializeBufferPool.Put(buffer)
			continue
		}
		dataLen := len(serializedData)
		if dataLen == 0 {
			ms.reportError(item.index, fmt.Errorf("serialization produced empty buffer"))
			serializeBufferPool.Put(buffer)
			continue
		}

		// Ensure we don't create massive packets
		if dataLen > 9000 { // Jumbo Ethernet MTU + header
			ms.reportError(item.index, fmt.Errorf("packet too large: %d bytes", dataLen))
			serializeBufferPool.Put(buffer)
			continue
		}

		// Safe copy with exact size allocation
		packet.packetBytes = make([]byte, dataLen)
		copy(packet.packetBytes, serializedData)

		if ms.StreamConfig.EnableMetrics {
			prepNs := time.Since(startPrepare).Nanoseconds()
			ms.metrics.prepareTime.Add(uint64(prepNs))
		}

		// Return the buffer to the pool after use
		serializeBufferPool.Put(buffer)

		// Send to output channel with non-blocking cancellation check
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

// GetNextResult returns the next result with improved buffer management
func (ms *MultiStreamSender) GetNextResult() *PacketSendResult {
	ms.mutex.Lock()
	defer ms.mutex.Unlock()

	// If we have buffered results, return one
	if len(ms.progressBuffer) > 0 {
		result := ms.progressBuffer[0]

		// Efficient slice management to avoid growing/copying the slice
		if len(ms.progressBuffer) > 1 {
			copy(ms.progressBuffer, ms.progressBuffer[1:])
			ms.progressBuffer = ms.progressBuffer[:len(ms.progressBuffer)-1]
		} else {
			ms.progressBuffer = ms.progressBuffer[:0]
		}

		return result
	}

	// Check if no more results are expected
	if ms.isComplete.Load() && ms.channelClosed.Load() {
		return nil
	}

	// Try to get multiple results at once to prevent blocking
	resultCount := 0
	maxResultsToBuffer := 100 // Get up to 100 at a time

	// Make sure we don't exceed our buffer capacity
	if cap(ms.progressBuffer) < maxResultsToBuffer {
		// Grow the buffer if needed
		newBuffer := make([]*PacketSendResult, 0, max(maxResultsToBuffer, ms.maxBufferSize))
		ms.progressBuffer = newBuffer
	}

	// Clear existing buffer (capacity remains)
	ms.progressBuffer = ms.progressBuffer[:0]

	// Fill the buffer without blocking
	for resultCount < maxResultsToBuffer {
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
	if len(flatData) == 0 || len(offsets) == 0 {
		return 0
	}

	totalArrays := len(offsets) / 2
	if totalArrays == 0 {
		return 0
	}

	// Pre-allocate the destination slice to avoid expensive reallocations
	ms.payloadMutex.Lock()
	initialLen := len(ms.Payloads)
	expectedFinalSize := initialLen + totalArrays
	if cap(ms.Payloads) < expectedFinalSize {
		newPayloads := make([][]byte, initialLen, expectedFinalSize)
		copy(newPayloads, ms.Payloads)
		ms.Payloads = newPayloads
	}
	ms.payloadMutex.Unlock()

	// For small datasets, process directly
	if totalArrays < 100 {
		ms.payloadMutex.Lock()
		defer ms.payloadMutex.Unlock()

		addedCount := 0
		for i := 0; i < totalArrays; i++ {
			startOffset := offsets[i*2]
			length := offsets[i*2+1]

			// Skip invalid offsets
			if startOffset < 0 || length <= 0 || startOffset+length > len(flatData) {
				continue
			}

			// Create and copy in one step
			payload := make([]byte, length)
			copy(payload, flatData[startOffset:startOffset+length])
			ms.Payloads = append(ms.Payloads, payload)
			addedCount++
		}
		return addedCount
	}

	// For large datasets, process in batches to limit memory usage
	const batchSize = 250000 // Process 250K payloads at a time
	totalAdded := 0

	for batchStart := 0; batchStart < totalArrays; batchStart += batchSize {
		batchEnd := min(batchStart+batchSize, totalArrays)

		// Create offset slice for just this batch
		batchOffsets := make([]int, (batchEnd-batchStart)*2)
		for i, j := 0, batchStart*2; i < len(batchOffsets); i, j = i+2, j+2 {
			batchOffsets[i] = offsets[j]
			batchOffsets[i+1] = offsets[j+1]
		}

		// Process this batch
		added := ms.processOrderedBatch(flatData, batchOffsets)
		totalAdded += added

		// Clear references
		batchOffsets = nil

		// Help GC between large batches
		if batchStart > 0 && batchStart%500000 == 0 {
			runtime.GC()
		}
	}

	return totalAdded
}

// Helper function to process a single batch of payloads while maintaining order
func (ms *MultiStreamSender) processOrderedBatch(flatData []byte, batchOffsets []int) int {
	// Reconstruct the byte slices for just this batch
	payloads := ReconstructByteArrays(flatData, batchOffsets)
	batchSize := len(payloads)

	// Calculate optimal parameters for parallel processing
	numWorkers := runtime.NumCPU() * 2
	if numWorkers > 32 {
		numWorkers = 32
	}

	var wg sync.WaitGroup

	// Calculate items per worker
	itemsPerWorker := (batchSize + numWorkers - 1) / numWorkers

	// Create a results array for this batch that maintains order
	results := make([][]byte, batchSize)

	// Process in parallel
	for w := 0; w < numWorkers; w++ {
		wg.Add(1)
		startIdx := w * itemsPerWorker
		endIdx := min(startIdx+itemsPerWorker, batchSize)

		if startIdx >= batchSize {
			wg.Done()
			continue
		}

		go func(start, end int) {
			defer wg.Done()

			for i := start; i < end; i++ {
				if payloads[i] == nil || len(payloads[i]) == 0 {
					continue
				}

				safeCopy := make([]byte, len(payloads[i]))
				copy(safeCopy, payloads[i])

				// Store at correct position
				results[i] = safeCopy

				// Clear reference to help GC
				payloads[i] = nil
			}
		}(startIdx, endIdx)
	}

	wg.Wait()

	// Help garbage collector
	payloads = nil

	// Add results to ms.Payloads in order
	addedCount := 0

	// Add results in smaller batches to reduce lock contention
	const addBatchSize = 10000
	currentBatch := make([][]byte, 0, addBatchSize)

	for i := 0; i < batchSize; i++ {
		if results[i] != nil {
			currentBatch = append(currentBatch, results[i])
			results[i] = nil // Help GC

			if len(currentBatch) >= addBatchSize {
				ms.payloadMutex.Lock()
				ms.Payloads = append(ms.Payloads, currentBatch...)
				addedCount += len(currentBatch)
				ms.payloadMutex.Unlock()

				// Reset batch
				currentBatch = currentBatch[:0]
			}
		}
	}

	// Add remaining items
	if len(currentBatch) > 0 {
		ms.payloadMutex.Lock()
		ms.Payloads = append(ms.Payloads, currentBatch...)
		addedCount += len(currentBatch)
		ms.payloadMutex.Unlock()

		// Reset batch (for GC)
		currentBatch = nil
	}

	// Help GC
	results = nil

	return addedCount
}

// reportError sends an error to the error channel in a non-blocking way
func (ms *MultiStreamSender) reportError(index int, err error) {
	if err == nil {
		return
	}

	// Create error result
	errResult := &PacketSendResult{
		Index:      index,
		TotalCount: len(ms.Payloads),
		Error:      err,
	}

	// Non-blocking send to error channel
	select {
	case ms.errorCh <- errResult:
		// Error sent successfully
	default:
		// Error channel full, increment dropped count
		if ms.metrics != nil {
			ms.metrics.packetsDropped.Add(1)
		}
	}
}

// safeCloseProgressCh ensures progressCh is closed exactly once
func (ms *MultiStreamSender) safeCloseProgressCh() {
	ms.closeOnce.Do(func() {
		ms.mutex.Lock()
		defer ms.mutex.Unlock()
		close(ms.progressCh)
		ms.channelClosed.Store(true)

		// Also close the error channel to stop the handler goroutine
		close(ms.errorCh)
	})
}

// RegisterFlattenedPayloads registers flattened payloads with a MultiStreamSender
// Internal function - not exported to Python
func RegisterFlattenedPayloads(sender *MultiStreamSender, flatData []byte, offsets []int) int {
	// Validate input parameters
	if flatData == nil || len(offsets) == 0 || sender == nil {
		return 0
	}

	numArrays := len(offsets) / 2
	if numArrays == 0 || len(offsets)%2 != 0 {
		return 0
	}

	totalDataSize := len(flatData)
	const maxSingleArraySize = 10 * 1024 * 1024 // 10MB max per array

	// For small data sets (under 10MB total), use the simple approach
	if totalDataSize < 10*1024*1024 && numArrays < 1000 {
		// Original approach for small data
		payloads := ReconstructByteArrays(flatData, offsets)
		count := 0
		for _, payload := range payloads {
			sender.AddPayload(payload)
			count++
		}
		return count
	}

	// For large data sets, process in batches to reduce peak memory usage
	count := 0
	maxBatchSize := 1000 // Process 1000 payloads at a time

	// Process in batches
	for batchStart := 0; batchStart < numArrays; batchStart += maxBatchSize {
		batchEnd := batchStart + maxBatchSize
		if batchEnd > numArrays {
			batchEnd = numArrays
		}

		// Create a batch of offsets
		batchOffsets := make([]int, 0, (batchEnd-batchStart)*2)
		for i := batchStart; i < batchEnd; i++ {
			batchOffsets = append(batchOffsets, offsets[i*2], offsets[i*2+1])
		}

		// Process this batch with memory safety checks
		func() {
			// Memory safety - recover from OOM conditions
			defer func() {
				if r := recover(); r != nil {
					LogDebug("Memory error in payload batch %d-%d: %v\n", batchStart, batchEnd, r)

					// If we hit memory issues, process one by one as a fallback
					for i := batchStart; i < batchEnd; i++ {
						startOffset := offsets[i*2]
						length := offsets[i*2+1]

						// Skip invalid offsets
						if startOffset < 0 || length <= 0 || startOffset+length > totalDataSize || length > maxSingleArraySize {
							continue
						}

						// Try to process this single payload with additional recovery
						func() {
							defer func() {
								if r := recover(); r != nil {
									// Individual payload caused OOM, skip it
									LogDebug("Skipping payload %d due to memory error: %v\n", i, r)
								}
							}()

							// Create a single slice
							slice := make([]byte, length)
							copy(slice, flatData[startOffset:startOffset+length])
							//fmt.Println("Payload slice length: ", len(slice))
							// Add to sender
							sender.AddPayload(slice)
							count++

							// Force incremental GC on high memory pressure
							if i%10 == 0 && runtime.NumGoroutine() > 1000 {
								runtime.GC()
							}
						}()
					}
				}
			}()

			// Try to process the batch normally
			payloads := ReconstructBatch(flatData, batchOffsets, batchEnd-batchStart)
			for _, payload := range payloads {
				if payload != nil && len(payload) > 0 {
					sender.AddPayload(payload)
					count++
				}
			}

			// Help GC after each large batch
			payloads = nil
			runtime.GC()
		}()

		// Periodic GC for very large datasets
		if batchStart > 0 && batchStart%10000 == 0 {
			LogDebug("Processed %d/%d payloads, triggering GC\n", batchStart, numArrays)
			runtime.GC()
		}
	}

	return count
}

// func detectMemorySwapPressure() (bool, error) {
// 	// Retrieve virtual memory stats
// 	vm, err := mem.VirtualMemory()
// 	if err != nil {
// 		return false, err
// 	}
// 	// Retrieve swap memory stats
// 	swap, err := mem.SwapMemory()
// 	if err != nil {
// 		return false, err
// 	}

// 	// Calculate physical memory usage in percent (provided by gopsutil)
// 	physicalUsagePercent := vm.UsedPercent

// 	// Compute swap used as a percentage of total physical memory.
// 	swapUsedPercentOfPhysical := (float64(swap.Used) / float64(vm.Total)) * 100

// 	// Compute available physical memory as a percentage.
// 	availablePercent := (float64(vm.Available) / float64(vm.Total)) * 100

// 	// Define thresholds (these can be adjusted to match your environment).
// 	const memUsageThreshold = 99.0  // 50.0 e.g. physical memory usage threshold in percent
// 	const swapUsageThreshold = 99.0 // 45.0 e.g. swap used relative to physical memory
// 	const availableThreshold = 99.0 // 40.0 e.g. available memory threshold in percent

// 	// Log the values for debugging or monitoring purposes.
// 	fmt.Printf("Physical Memory Usage: %.1f%%\n", physicalUsagePercent)
// 	fmt.Printf("Swap Used as %% of Physical Memory: %.1f%%\n", swapUsedPercentOfPhysical)
// 	fmt.Printf("Available Physical Memory: %.1f%%\n", availablePercent)

// 	// If physical memory usage is high and either swap usage is high or available memory is very low,
// 	// then we consider the system under heavy memory pressure.
// 	if physicalUsagePercent >= memUsageThreshold &&
// 		(swapUsedPercentOfPhysical >= swapUsageThreshold && availablePercent <= availableThreshold) {
// 		fmt.Println("System is under memory pressure (high physical memory usage and/or swap usage).")
// 		return true, nil
// 	}

// 	return false, nil
// }
