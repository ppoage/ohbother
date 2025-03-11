package ohbother

/*
#cgo pkg-config: python3
#define Py_LIMITED_API
#include <Python.h>
#include <stdlib.h>

*/
import "C"
import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"runtime"
	"sync"
)

// HashResult represents the result of hash computation
type HashResult struct {
	ShortestHash string
	LongestHash  string
	Count        int
}

// ComputeHashesForByteSlices computes SHA-256 hashes for all byte slices
// and returns the lexicographically shortest and longest hashes.
// This function takes raw byte slices directly from Go.
func ComputeHashesForByteSlices(slices [][]byte) *HashResult {
	if len(slices) == 0 {
		return &HashResult{
			ShortestHash: "",
			LongestHash:  "",
			Count:        0,
		}
	}

	// Use all available CPUs for maximum performance
	numWorkers := runtime.NumCPU()
	chunkSize := (len(slices) + numWorkers - 1) / numWorkers

	type hashPair struct {
		shortest string
		longest  string
	}

	results := make(chan hashPair, numWorkers)
	var wg sync.WaitGroup

	// Process chunks in parallel
	for i := 0; i < numWorkers; i++ {
		wg.Add(1)
		startIdx := i * chunkSize
		endIdx := startIdx + chunkSize
		if endIdx > len(slices) {
			endIdx = len(slices)
		}

		go func(start, end int) {
			defer wg.Done()

			// Initialize with empty values
			localShortest := ""
			localLongest := ""

			for idx := start; idx < end; idx++ {
				// Compute SHA-256 hash
				hash := sha256.Sum256(slices[idx])
				hashHex := hex.EncodeToString(hash[:])

				// Update shortest hash
				if localShortest == "" || hashHex < localShortest {
					localShortest = hashHex
				}

				// Update longest hash
				if hashHex > localLongest {
					localLongest = hashHex
				}
			}

			// Send results back
			results <- hashPair{shortest: localShortest, longest: localLongest}
		}(startIdx, endIdx)
	}

	// Wait for all workers to complete
	wg.Wait()
	close(results)

	// Find global shortest and longest
	globalShortest := ""
	globalLongest := ""

	for pair := range results {
		// Update global shortest
		if globalShortest == "" || pair.shortest < globalShortest {
			globalShortest = pair.shortest
		}

		// Update global longest
		if pair.longest > globalLongest {
			globalLongest = pair.longest
		}
	}

	return &HashResult{
		ShortestHash: globalShortest,
		LongestHash:  globalLongest,
		Count:        len(slices),
	}
}

// ProcessPayloads processes a batch of payloads as received from Python.
// This is the main entry point called from Python when sending large datasets.
func ProcessPayloads(pyPayload interface{}) *HashResult {
	// Convert Python data to Go data in one step
	payloads := PayloadNative(pyPayload)
	if len(payloads) == 0 {
		return &HashResult{
			ShortestHash: "",
			LongestHash:  "",
			Count:        0,
		}
	}

	fmt.Printf("Processing %d payloads in Go\n", len(payloads))

	// Process the payloads directly in Go
	return ComputeHashesForByteSlices(payloads)
}
