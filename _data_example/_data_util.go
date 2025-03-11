package ohbother

/*
#cgo pkg-config: python3
#define Py_LIMITED_API
#include <Python.h>
#include <stdlib.h>
*/
import "C"
import (
	"fmt"
	"sync"
	"sync/atomic"
)

// RegisterSlice with sharded registry.
var (
	registryShards  = 128 // Increased for better concurrency
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
	fmt.Printf("Initialized registry with %d shards\n", registryShards)
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
