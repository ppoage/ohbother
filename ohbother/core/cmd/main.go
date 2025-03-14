package main

import (
	"fmt"
	"ohbother/src/config"
	"ohbother/src/transmit"
	"runtime"
	"sort"
	"sync"
	"time"
)

type Config = config.Config

var NewMultiStreamSender = transmit.NewMultiStreamSender
var NewDefaultConfig = config.NewDefaultConfig
var LogDebug = config.LogDebug

// Constants for maximum load
const (
	// Test configuration
	PACKET_COUNT = 35_000_000
	//PACKET_COUNT = 1_000_000
	//PACKET_COUNT = 1_000
	PAYLOAD_SIZE = 60
	RATE_LIMIT   = 200_000

	// Worker configuration
	WORKER_COUNT    = 12
	STREAM_COUNT    = 4
	BUFFER_COUNT    = 1000 // Channel buffer size
	REPORT_INTERVAL = 1000 // How often to report progress
	TURNSTILE_BURST = 16   // Burst size for rate limiting

	// Network configuration
	SNAP_LEN       = 1500
	PROMISC        = true
	BUFFER_SIZE    = 1 * 1024 * 1024
	IMMEDIATE_MODE = true
	RECEIVE_ENABLE = false
	SRC_MAC        = "1a:c0:9f:b8:84:45"
	DST_MAC        = "3c:7c:3f:86:19:10"
	SRC_IP         = "192.168.50.105"
	DST_IP         = "192.168.50.1"
	SRC_PORT       = 8443
	DST_PORT       = 8443
	INTERFACE      = "en0"
	BPF_FILTER     = "udp and dst port 8443"

	// Advanced settings
	CPU_PINNING    = false
	DISABLE_ORDER  = true
	ENABLE_METRICS = true
)

// flatten_byte_arrays_serial flattens a [][]byte into a single []byte and
// generates an offsets slice where each array's offsets are stored as [start, length] pairs.
func flatten_byte_arrays_serial(arrays [][]byte) ([]byte, []int) {
	total_length := 0
	num_arrays := len(arrays)
	// Allocate offsets with two integers per array.
	offsets := make([]int, num_arrays*2)

	// Compute the total length and record start offset and length.
	for i, arr := range arrays {
		offsets[i*2] = total_length // start offset
		offsets[i*2+1] = len(arr)   // length of the array
		total_length += len(arr)
	}

	flat_data := make([]byte, total_length)
	current_pos := 0
	for _, arr := range arrays {
		copy(flat_data[current_pos:], arr)
		current_pos += len(arr)
	}

	return flat_data, offsets
}

// flatten_byte_arrays flattens a [][]byte into a single []byte and produces offsets as [start, length] pairs.
// It uses parallel processing for large datasets and falls back to the serial version for small ones.
func flatten_byte_arrays(arrays [][]byte) ([]byte, []int) {
	if len(arrays) == 0 {
		return []byte{}, []int{}
	}

	// For small datasets, use the serial version.
	if len(arrays) < 10000 {
		return flatten_byte_arrays_serial(arrays)
	}

	num_workers := WORKER_COUNT
	if num_workers <= 0 {
		num_workers = runtime.NumCPU()
	}
	if len(arrays) < num_workers {
		num_workers = len(arrays)
	}

	// Calculate chunk size for each worker.
	chunk_size := (len(arrays) + num_workers - 1) / num_workers

	// Structure for worker results.
	type chunk_result struct {
		flat_data []byte
		offsets   []int // Offsets are [start, length] pairs for the chunk.
		chunk_id  int
		count     int // Number of arrays processed in this chunk.
	}

	result_chan := make(chan chunk_result, num_workers)
	var wg sync.WaitGroup
	start_time := time.Now()

	// Launch workers.
	for i := 0; i < num_workers; i++ {
		start_idx := i * chunk_size
		if start_idx >= len(arrays) {
			break
		}
		end_idx := start_idx + chunk_size
		if end_idx > len(arrays) {
			end_idx = len(arrays)
		}

		wg.Add(1)
		go func(chunk_id int, chunk [][]byte) {
			defer wg.Done()
			chunk_start := time.Now()

			flat_data, offsets := flatten_byte_arrays_serial(chunk)
			total_bytes := len(flat_data)

			chunk_duration := time.Since(chunk_start)
			fmt.Printf("Chunk %d: Flattened %d items (%d bytes) in %.3fs\n",
				chunk_id, len(chunk), total_bytes, chunk_duration.Seconds())

			result_chan <- chunk_result{
				flat_data: flat_data,
				offsets:   offsets,
				chunk_id:  chunk_id,
				count:     len(chunk),
			}
		}(i, arrays[start_idx:end_idx])
	}

	// Close the result channel when all workers are done.
	go func() {
		wg.Wait()
		close(result_chan)
	}()

	// Collect and sort results by chunk_id.
	results := make([]chunk_result, 0, num_workers)
	for result := range result_chan {
		results = append(results, result)
	}

	sort.Slice(results, func(i, j int) bool {
		return results[i].chunk_id < results[j].chunk_id
	})

	// Calculate total size and allocate output arrays.
	total_size := 0
	for _, res := range results {
		total_size += len(res.flat_data)
	}

	final_data := make([]byte, total_size)
	// final_offsets will have two entries per original array.
	final_offsets := make([]int, len(arrays)*2)

	current_pos := 0
	array_index := 0

	// Combine results from each chunk.
	for _, res := range results {
		copy(final_data[current_pos:], res.flat_data)

		// Adjust offsets from this chunk: update start offset relative to final_data.
		for i := 0; i < res.count; i++ {
			final_offsets[array_index*2] = res.offsets[i*2] + current_pos
			final_offsets[array_index*2+1] = res.offsets[i*2+1] // length remains the same
			array_index++
		}
		current_pos += len(res.flat_data)
	}

	duration := time.Since(start_time)
	fmt.Printf("Parallel flattening: Combined %d items (%d bytes) in %.3fs\n",
		len(arrays), len(final_data), duration.Seconds())

	return final_data, final_offsets
}

func benchmarkStreamSend(cfg *Config, packetCount int, payloadSize int, rateLimit int) (float64, error) {
	fmt.Printf("\n=== Starting BenchmarkStreamSend ===\n")
	fmt.Printf("Packets: %d, Size: %d, Rate: %d\n", packetCount, payloadSize, rateLimit)

	// Time: Generate payloads
	start := time.Now()
	payloads := make([][]byte, packetCount)
	for i := 0; i < packetCount; i++ {
		buf := make([]byte, payloadSize)
		for j := range buf {
			buf[j] = byte((i + j) % 256) // Simple pattern, not random
		}
		payloads[i] = buf
	}
	genTime := time.Since(start)
	fmt.Printf("Generated %d payloads in %.3fs\n", packetCount, genTime.Seconds())

	// Time: Create sender
	start = time.Now()
	sender := NewMultiStreamSender(cfg, rateLimit)
	sender.SetStreamConfig(WORKER_COUNT, STREAM_COUNT, BUFFER_COUNT, REPORT_INTERVAL)
	sender.SetAdvancedConfig(CPU_PINNING, DISABLE_ORDER, TURNSTILE_BURST, ENABLE_METRICS)
	setupTime := time.Since(start)
	fmt.Printf("Sender setup in %.3fs\n", setupTime.Seconds())

	// Time: Add payloads
	start = time.Now()
	// Remove type assertion, use FastConvertPayloads directly
	converted_payloads, offsets := flatten_byte_arrays(payloads)
	addTime := time.Since(start)
	fmt.Printf("Converted %d payloads in %.3fs\n", len(converted_payloads), addTime.Seconds())
	payloads_added := sender.AddPayloadsFlat(converted_payloads, offsets)
	fmt.Printf("Added %d payloads in %.3fs\n", payloads_added, addTime.Seconds())

	// Time: Send
	start = time.Now()
	if err := sender.Send(); err != nil {
		return 0, fmt.Errorf("send error: %v", err)
	}

	// Wait for completion while showing progress
	var lastReport time.Time
	const reportInterval = time.Second
	for !sender.IsComplete() {
		if time.Since(lastReport) >= reportInterval {
			sent := sender.GetSentCount()
			errors := sender.GetErrorCount()
			elapsed := time.Since(start)
			rate := float64(sent) / elapsed.Seconds()
			completion_status := sender.IsComplete()
			fmt.Printf("Progress: %d sent, %d errors, %.0f pps, complete: %t \n", sent, errors, rate, completion_status)
			lastReport = time.Now()
		}
		time.Sleep(100 * time.Millisecond)
	}

	sendTime := time.Since(start)

	// Final stats
	sent := sender.GetSentCount()
	errors := sender.GetErrorCount()
	totalTime := genTime + setupTime + addTime + sendTime
	rate := float64(sent) / sendTime.Seconds()

	fmt.Printf("\n=== Benchmark Complete ===\n")
	fmt.Printf("Generate time: %.3fs\n", genTime.Seconds())
	fmt.Printf("Setup time:    %.3fs\n", setupTime.Seconds())
	fmt.Printf("Convert time:  %.3fs\n", addTime.Seconds())
	fmt.Printf("Send time:     %.3fs\n", sendTime.Seconds())
	fmt.Printf("Total time:    %.3fs\n", totalTime.Seconds())
	fmt.Printf("Packets sent:  %d\n", sent)
	fmt.Printf("Errors:        %d\n", errors)
	fmt.Printf("Final rate:    %.0f pps\n", rate)

	if metrics := sender.GetMetrics(); metrics != nil {
		fmt.Printf("\nDetailed Metrics:\n")
		for k, v := range metrics {
			fmt.Printf("%-20s %d\n", k+":", v)
		}
	}

	return rate, nil
}

func main() {
	fmt.Println("\n=== UDP Multi-Stream Benchmark ===")
	fmt.Printf("Configuration:\n")
	fmt.Printf("  Packets: %d, Size: %d bytes, Rate: %d pps\n", PACKET_COUNT, PAYLOAD_SIZE, RATE_LIMIT)
	fmt.Printf("  Workers: %d, Streams: %d\n", WORKER_COUNT, STREAM_COUNT)
	fmt.Printf("  Interface: %s\n", INTERFACE)

	// Create configuration (remove ohbother. prefix)
	cfg, err := NewDefaultConfig(
		INTERFACE,
		SRC_MAC,
		DST_MAC,
		SRC_IP,
		DST_IP,
		SRC_PORT,
		DST_PORT,
		BPF_FILTER,
		SNAP_LEN,
		PROMISC,
		BUFFER_SIZE,
		IMMEDIATE_MODE,
	)
	cfg.EnableDebug(4)
	//cfg.Debug.Level = 4
	LogDebug("Printing LogDebug")
	if err != nil {
		fmt.Printf("Error creating config: %v\n", err)
		return
	}

	// Run benchmark (remove ohbother. prefix)
	rate, err := benchmarkStreamSend(cfg, PACKET_COUNT, PAYLOAD_SIZE, RATE_LIMIT)
	if err != nil {
		fmt.Printf("Benchmark failed: %v\n", err)
		return
	}

	fmt.Printf("\nBenchmark complete: %.2f packets/second\n", rate)
}
