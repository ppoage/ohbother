package ohbother

import (
	"crypto/rand"
	"fmt"
	"time"
)

func BenchmarkSend(cfg *Config, packetCount int, payloadSize int, rateLimit int) (float64, error) {
	// Debug configuration
	LogInfo("Starting BenchmarkSend:\n")
	LogInfo("  - Packet Count: %d\n", packetCount)
	LogInfo("  - Payload Size: %d\n", payloadSize)
	LogInfo("  - Interface: %s\n", cfg.Pcap.Iface)

	// Generate payloads
	payloads := make([][]byte, packetCount)
	for i := 0; i < packetCount; i++ {
		buf := make([]byte, payloadSize)
		if _, err := rand.Read(buf); err != nil {
			return 0, fmt.Errorf("error generating random payload: %v", err)
		}
		payloads[i] = buf
	}

	LogDebug("Generated %d payloads of %d bytes each\n", packetCount, payloadSize)

	// Start benchmark
	LogInfo("Starting benchmark...\n")
	start := time.Now()

	// Call SendPacketsNative with strongly-typed [][]byte
	if err := sendPacketsNative(cfg, payloads, rateLimit); err != nil {
		return 0, err
	}

	elapsed := time.Since(start).Seconds()
	rate := float64(packetCount) / elapsed
	return rate, nil
}

// BenchmarkReceiveAsync starts an asynchronous receive operation for the specified duration (in seconds)
// and returns an AsyncReceiver pointer. Later, the caller can call Result() on the AsyncReceiver
// to obtain the full slice of received UDP payloads (each a []byte) or an error.
func BenchmarkReceiveAsync(cfg *Config, duration float64) *PacketReceiver {
	return PacketReceiverByTime(cfg, duration)
}
