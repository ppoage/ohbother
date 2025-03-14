package ohbother

import (
	"fmt"
	"runtime"
	"sync"
	"sync/atomic"
	"time"
)

// Registry for byte slices with sharded locking
var (
	registryShards            = 128
	shardedRegistry           []*registryShard
	nextHandle                int64        = 1
	reconstructionWorkerCount atomic.Int32 = *func() *atomic.Int32 {
		i := new(atomic.Int32)
		// Default to CPU*2 workers
		i.Store(int32(runtime.NumCPU() * 2))
		return i
	}()
)

// Each shard protects its own map
type registryShard struct {
	sync.RWMutex
	data map[int64][]byte
}

// RegistryStats provides information about the registry
type RegistryStats struct {
	ItemCount   int   `json:"item_count"`
	TotalBytes  int64 `json:"total_bytes"`
	MemoryUsage int64 `json:"memory_usage"`
	ShardCount  int   `json:"shard_count"`
	TimeStamp   int64 `json:"timestamp"`
}

// SetUtilWorkers safely sets the worker count for ReconstructByteArrays
func SetUtilWorkers(count int) {
	if count > 0 {
		reconstructionWorkerCount.Store(int32(count))
	}
}

// GetUtilWorkers safely retrieves the current worker count
func GetUtilWorkers() int {
	return int(reconstructionWorkerCount.Load())
}

func init() {
	// Initialize sharded registry
	shardedRegistry = make([]*registryShard, registryShards)
	for i := 0; i < registryShards; i++ {
		shardedRegistry[i] = &registryShard{
			data: make(map[int64][]byte),
		}
	}
	LogDebug("Initialized registry with %d shards\n", registryShards)
}

// newSliceByteFromBytes creates a new byte slice in Go memory
func newSliceByteFromBytes(data []byte) int64 {
	// Make a copy to ensure memory safety
	copied := make([]byte, len(data))
	copy(copied, data)

	// Get a unique handle
	handle := atomic.AddInt64(&nextHandle, 1)

	// Store in registry
	shard := int(handle) % registryShards
	shardedRegistry[shard].Lock()
	shardedRegistry[shard].data[handle] = copied
	shardedRegistry[shard].Unlock()

	return handle
}

// getSliceBytes retrieves a byte slice by its handle
func getSliceBytes(handle int64) ([]byte, error) {
	shard := int(handle) % registryShards
	shardedRegistry[shard].RLock()
	data, exists := shardedRegistry[shard].data[handle]
	shardedRegistry[shard].RUnlock()

	if !exists {
		return nil, fmt.Errorf("handle %d not found in registry", handle)
	}
	return data, nil
}

// deleteSliceBytes removes a byte slice from the registry
func deleteSliceBytes(handle int64) {
	shard := int(handle) % registryShards
	shardedRegistry[shard].Lock()
	delete(shardedRegistry[shard].data, handle)
	shardedRegistry[shard].Unlock()
}

// GetRegistryStats returns statistics about the registry
func GetRegistryStats() *RegistryStats {
	stats := &RegistryStats{
		ShardCount: registryShards,
		TimeStamp:  time.Now().UnixNano(),
	}

	// Collect stats from all shards
	for i := 0; i < registryShards; i++ {
		shardedRegistry[i].RLock()
		stats.ItemCount += len(shardedRegistry[i].data)
		for _, data := range shardedRegistry[i].data {
			stats.TotalBytes += int64(len(data))
		}
		shardedRegistry[i].RUnlock()
	}

	// Estimate memory usage (bytes + overhead)
	stats.MemoryUsage = stats.TotalBytes + int64(stats.ItemCount*16)

	return stats
}

// ClearRegistry removes all items from the registry
func ClearRegistry() {
	for i := 0; i < registryShards; i++ {
		shardedRegistry[i].Lock()
		shardedRegistry[i].data = make(map[int64][]byte)
		shardedRegistry[i].Unlock()
	}
	// Reset handle counter to avoid overflow on long benchmarks
	atomic.StoreInt64(&nextHandle, 1)

	// Force garbage collection
	runtime.GC()
}

// batchStoreByteSlices stores multiple byte slices in the registry and returns their handles
func batchStoreByteSlices(slices [][]byte) []int64 {
	if len(slices) == 0 {
		return []int64{} // Return empty slice instead of nil for better Python compatibility
	}

	// Create result array
	result := make([]int64, len(slices))

	// Use multiple workers for large batches
	numWorkers := runtime.NumCPU()
	if numWorkers > 8 {
		numWorkers = 8 // Cap at 8 workers
	}

	// Process in parallel for large batches
	if len(slices) > 1000 {
		var wg sync.WaitGroup
		batchSize := (len(slices) + numWorkers - 1) / numWorkers

		for w := 0; w < numWorkers; w++ {
			startIdx := w * batchSize
			endIdx := startIdx + batchSize
			if endIdx > len(slices) {
				endIdx = len(slices)
			}

			if startIdx >= len(slices) {
				continue
			}

			wg.Add(1)
			go func(start, end int) {
				defer wg.Done()
				for i := start; i < end; i++ {
					// Store in registry and get handle
					result[i] = newSliceByteFromBytes(slices[i])
				}
			}(startIdx, endIdx)
		}

		wg.Wait()
	} else {
		// Process sequentially for small batches
		for i, slice := range slices {
			result[i] = newSliceByteFromBytes(slice)
		}
	}

	return result
}

// StoreByteSlice stores a single byte slice in the registry and returns its handle
func StoreByteSlice(data []byte) int64 {
	return newSliceByteFromBytes(data)
}

// GetByteSlice retrieves a byte slice from the registry by its handle
func GetByteSlice(handle int64) []byte {
	data, err := getSliceBytes(handle)
	if err != nil {
		return []byte{} // Return empty slice if not found
	}
	return data
}

// DeleteByteSlice removes a byte slice from the registry
func DeleteByteSlice(handle int64) {
	deleteSliceBytes(handle)
}

// ReconstructByteArrays rebuilds a [][]byte from flattened data and offsets
func ReconstructByteArrays(flatData []byte, offsets []int) [][]byte {
	// Validate input parameters first
	if flatData == nil {
		return [][]byte{}
	}

	// Offsets come in pairs: (start, length)
	numArrays := len(offsets) / 2
	if numArrays == 0 || len(offsets)%2 != 0 {
		return [][]byte{}
	}

	// Pre-allocate result slice with exact capacity needed
	result := make([][]byte, numArrays)

	// For small arrays, use the sequential version to avoid goroutine overhead
	if numArrays < 100 {
		return reconstructSequential(flatData, offsets, numArrays)
	}

	// Get worker count from atomic variable (thread-safe)
	numWorkers := GetUtilWorkers() * 2

	// Cap at reasonable maximum
	if numWorkers > 32 {
		numWorkers = 32
	}

	// Ensure we don't create more workers than needed
	if numWorkers > numArrays/100 {
		numWorkers = max(1, numArrays/100)
	}

	//fmt.Printf("Number of workers: %d\n", numWorkers)

	// Pre-compute total bytes to estimate memory usage
	totalBytes := 0
	maxArraySize := 0
	for i := 0; i < numArrays; i++ {
		length := offsets[i*2+1]
		if length > 0 {
			totalBytes += length
			maxArraySize = max(maxArraySize, length)
		}
	}

	// LogDebug("ReconstructByteArrays: Reconstructing %d byte arrays with %d workers, total bytes: %d, max array size: %d\n",
	// 	numArrays, numWorkers, totalBytes, maxArraySize)

	// Use worker pool pattern with buffered channels for better throughput
	type workItem struct {
		index       int
		startOffset int
		length      int
	}

	// Determine batch size based on array characteristics
	// This is a key optimization for throughput
	batchSize := 1000
	if numArrays > 1_000_000 {
		batchSize = 5000
	}

	// Create channels with optimized buffer sizes
	jobs := make(chan workItem, min(numArrays, 100_000))
	var wg sync.WaitGroup
	var errorCount atomic.Int32

	// Launch worker pool
	for w := 0; w < numWorkers; w++ {
		wg.Add(1)
		go func() {
			defer func() {
				wg.Done()
				if r := recover(); r != nil {
					LogDebug("Recovered from panic in ReconstructByteArrays worker: %v", r)
					errorCount.Add(1)
				}
			}()

			// Pre-allocate reusable buffer for each worker
			// This significantly reduces small allocations and GC pressure
			scratchBuffer := make([]byte, maxArraySize)

			// Process jobs until channel is closed
			for job := range jobs {
				// Skip invalid ranges without panicking
				if job.startOffset < 0 || job.length <= 0 ||
					job.startOffset+job.length > len(flatData) {
					result[job.index] = make([]byte, 0)
					continue
				}

				// Create slice with exact needed size
				if job.length > cap(scratchBuffer) {
					scratchBuffer = make([]byte, job.length)
				}
				buffer := scratchBuffer[:job.length]

				// Copy data from flat buffer
				copy(buffer, flatData[job.startOffset:job.startOffset+job.length])

				// Create new slice to store in result (don't share the scratch buffer)
				resultSlice := make([]byte, job.length)
				copy(resultSlice, buffer)
				result[job.index] = resultSlice
			}
		}()
	}

	// Queue jobs in chunks to reduce channel pressure
	// This is critical for extremely large workloads
	for batchStart := 0; batchStart < numArrays; batchStart += batchSize {
		batchEnd := min(batchStart+batchSize, numArrays)

		for i := batchStart; i < batchEnd; i++ {
			startOffset := offsets[i*2]
			length := offsets[i*2+1]

			jobs <- workItem{
				index:       i,
				startOffset: startOffset,
				length:      length,
			}
		}
	}

	close(jobs)
	wg.Wait()

	if errorCount.Load() > 0 {
		LogDebug("ReconstructByteArrays encountered %d errors during processing", errorCount.Load())
	}

	return result
}

// Sequential version for small arrays or fallback
func reconstructSequential(flatData []byte, offsets []int, numArrays int) [][]byte {
	result := make([][]byte, numArrays)

	for i := 0; i < numArrays; i++ {
		start := offsets[i*2]
		length := offsets[i*2+1]

		// Bounds checking
		if start < 0 || length <= 0 || start+length > len(flatData) {
			result[i] = make([]byte, 0)
			continue
		}

		slice := make([]byte, length)
		copy(slice, flatData[start:start+length])
		result[i] = slice
	}

	return result
}

// BatchStoreByteSlicesFlat stores multiple byte slices from a flattened representation
func BatchStoreByteSlicesFlat(flatData []byte, offsets []int) []int64 {
	// Reconstruct the byte slices
	slices := ReconstructByteArrays(flatData, offsets)

	// Store them in the registry
	return batchStoreByteSlices(slices)
}

// BatchConvertPythonBytesToSlices converts a list of Python byte arrays to Go handles
func BatchConvertPythonBytesToSlices(rawBytes [][]byte, numWorkers int) []int64 {
	size := len(rawBytes)
	if size == 0 {
		LogDebug("BatchConvertPythonBytesToSlices: No input bytes provided\n")
		return []int64{}
	}

	// Create result array
	result := make([]int64, size)

	// Determine optimal worker count
	if numWorkers <= 0 {
		numWorkers = runtime.NumCPU() * 4 // Default to 4x CPU cores
	}
	if numWorkers > size {
		numWorkers = size
	}

	LogDebug("BatchConvertPythonBytesToSlices: Converting %d byte arrays with %d workers\n", size, numWorkers)

	// Use a wait group to synchronize workers
	var wg sync.WaitGroup

	// Calculate batch size for each worker
	batchSize := (size + numWorkers - 1) / numWorkers

	// Process in batches using goroutines
	for w := 0; w < numWorkers; w++ {
		startIdx := w * batchSize
		endIdx := startIdx + batchSize
		if endIdx > size {
			endIdx = size
		}

		if startIdx >= size {
			continue
		}

		wg.Add(1)
		go func(start, end int) {
			defer wg.Done()

			// Process each item in the batch
			for i := start; i < end; i++ {
				// Copy data for safety
				copied := make([]byte, len(rawBytes[i]))
				copy(copied, rawBytes[i])

				// Store in registry
				result[i] = newSliceByteFromBytes(copied)
			}
		}(startIdx, endIdx)
	}

	// Wait for all goroutines to complete
	wg.Wait()

	LogDebug("BatchConvertPythonBytesToSlices: Completed converting %d byte arrays\n", size)
	return result
}
