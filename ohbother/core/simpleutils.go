package ohbother

import (
	"runtime"
	"sync"
	"sync/atomic"
)

// Registry for byte slices with sharded locking
var (
	registryShards  = 128
	shardedRegistry []*registryShard
	nextHandle      int64 = 1
)

// Each shard protects its own map
type registryShard struct {
	sync.RWMutex
	data map[int64][]byte
}

func init() {
	// Initialize sharded registry
	shardedRegistry = make([]*registryShard, registryShards)
	for i := 0; i < registryShards; i++ {
		shardedRegistry[i] = &registryShard{
			data: make(map[int64][]byte),
		}
	}
	LogDebug("Initialized registry with %d shards", registryShards)
}

// NewSliceByteFromBytes creates a new byte slice in Go memory
func NewSliceByteFromBytes(data []byte) int64 {
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

// GetSliceBytes retrieves a byte slice by its handle
func GetSliceBytes(handle int64) ([]byte, bool) {
	shard := int(handle) % registryShards

	shardedRegistry[shard].RLock()
	data, exists := shardedRegistry[shard].data[handle]
	shardedRegistry[shard].RUnlock()

	return data, exists
}

// DeleteSliceBytes removes a byte slice from the registry
func DeleteSliceBytes(handle int64) {
	shard := int(handle) % registryShards

	shardedRegistry[shard].Lock()
	delete(shardedRegistry[shard].data, handle)
	shardedRegistry[shard].Unlock()
}

// BatchConvertPythonBytesToSlices converts a list of Python byte arrays to Go handles
func BatchConvertPythonBytesToSlices(rawBytes [][]byte, numWorkers int) []int64 {
	size := len(rawBytes)
	if size == 0 {
		LogDebug("BatchConvertPythonBytesToSlices: No input bytes provided")
		return nil
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

	LogDebug("BatchConvertPythonBytesToSlices: Converting %d byte arrays with %d workers", size, numWorkers)

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
				result[i] = NewSliceByteFromBytes(copied)
			}
		}(startIdx, endIdx)
	}

	// Wait for all goroutines to complete
	wg.Wait()

	LogDebug("BatchConvertPythonBytesToSlices: Completed converting %d byte arrays", size)
	return result
}
