package ohbother

import (
	"runtime"
	"sync"
)

// reconstructBatch is a memory-efficient version of reconstructing a batch of arrays
func ReconstructBatch(flatData []byte, offsets []int, numArrays int) [][]byte {
	result := make([][]byte, numArrays)

	// Use worker pool if large enough batch
	if numArrays >= 100 {
		// Similar to ReconstructByteArrays but with stricter memory limits
		numWorkers := runtime.NumCPU()
		if numWorkers > 4 {
			numWorkers = 4 // Limit workers to reduce memory pressure
		}

		var wg sync.WaitGroup
		itemsPerWorker := (numArrays + numWorkers - 1) / numWorkers

		for w := 0; w < numWorkers; w++ {
			startIdx := w * itemsPerWorker
			endIdx := startIdx + itemsPerWorker
			if endIdx > numArrays {
				endIdx = numArrays
			}

			if startIdx >= numArrays {
				continue
			}

			wg.Add(1)
			go func(start, end int) {
				defer func() {
					wg.Done()
					if r := recover(); r != nil {
						LogDebug("Memory error in batch worker: %v\n", r)
					}
				}()

				for i := start; i < end; i++ {
					startOffset := offsets[i*2]
					length := offsets[i*2+1]

					// Skip invalid entries
					if startOffset < 0 || length <= 0 || startOffset+length > len(flatData) {
						result[i] = make([]byte, 0)
						continue
					}

					// Create slice with capacity check
					if length > 100*1024*1024 { // 100MB sanity limit
						LogDebug("Skipping oversized entry: %d bytes\n", length)
						result[i] = make([]byte, 0)
						continue
					}

					slice := make([]byte, length)
					copy(slice, flatData[startOffset:startOffset+length])
					result[i] = slice
				}
			}(startIdx, endIdx)
		}

		wg.Wait()
	} else {
		// Process sequentially for small batches
		for i := 0; i < numArrays; i++ {
			startOffset := offsets[i*2]
			length := offsets[i*2+1]

			// Skip invalid entries
			if startOffset < 0 || length <= 0 || startOffset+length > len(flatData) {
				result[i] = make([]byte, 0)
				continue
			}

			slice := make([]byte, length)
			copy(slice, flatData[startOffset:startOffset+length])
			result[i] = slice
		}
	}

	return result
}
