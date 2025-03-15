package ohbother

import (
	"bytes"
	"math/rand"
	"runtime"
	"testing"
	"time"
)

func TestReconstructByteArrays(t *testing.T) {
	// Set up random source with modern approach (not using deprecated rand.Seed)
	rng := rand.New(rand.NewSource(time.Now().UnixNano()))

	// Helper function to create test data
	createTestData := func(count int, minSize, maxSize int) ([][]byte, []byte, []int) {
		original := make([][]byte, count)
		totalSize := 0

		// Generate random byte arrays
		for i := 0; i < count; i++ {
			size := minSize
			if maxSize > minSize {
				size = minSize + rng.Intn(maxSize-minSize)
			}

			data := make([]byte, size)
			for j := 0; j < size; j++ {
				data[j] = byte(rng.Intn(256))
			}
			original[i] = data
			totalSize += size
		}

		// Create flattened data and offsets
		flatData := make([]byte, totalSize)
		offsets := make([]int, count*2)

		pos := 0
		for i, arr := range original {
			offsets[i*2] = pos        // start
			offsets[i*2+1] = len(arr) // length
			copy(flatData[pos:], arr)
			pos += len(arr)
		}

		return original, flatData, offsets
	}

	// Helper to verify results
	verifyResults := func(t *testing.T, original, reconstructed [][]byte, testName string) {
		t.Helper()

		if len(original) != len(reconstructed) {
			t.Errorf("%s: length mismatch - expected %d, got %d",
				testName, len(original), len(reconstructed))
			return
		}

		for i := 0; i < len(original); i++ {
			if !bytes.Equal(original[i], reconstructed[i]) {
				t.Errorf("%s: content mismatch at index %d - expected len=%d, got len=%d",
					testName, i, len(original[i]), len(reconstructed[i]))
				return
			}
		}
	}

	// Test cases
	testCases := []struct {
		name    string
		count   int
		minSize int
		maxSize int
	}{
		{"Empty", 0, 0, 0},
		{"Tiny", 5, 10, 20},
		{"Small", 50, 10, 100},
		{"Medium", 500, 10, 1000},
		{"Large", 5000, 10, 100},
		{"Mixed Sizes", 1000, 1, 5000},
		{"Very Small", 10000, 1, 10},
		{"Many Small", 50000, 30, 1400},
		{"Huge Mix", 500_000, 30, 1400},
		{"Massive Mix", 40_000_000, 30, 80},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			original, flatData, offsets := createTestData(tc.count, tc.minSize, tc.maxSize)

			// Measure reconstruction time
			start := time.Now()
			reconstructed := ReconstructByteArrays(flatData, offsets)
			elapsed := time.Since(start)

			verifyResults(t, original, reconstructed, tc.name)

			// Log performance information for larger tests
			if tc.count >= 1000 {
				t.Logf("%s: Processed %d arrays in %v (%.2f arrays/sec)",
					tc.name, tc.count, elapsed, float64(tc.count)/elapsed.Seconds())
			}
		})
	}

	// Test edge cases
	t.Run("Nil Data", func(t *testing.T) {
		result := ReconstructByteArrays(nil, []int{0, 5})
		if len(result) != 0 {
			t.Errorf("Expected empty result for nil data, got %d elements", len(result))
		}
	})

	t.Run("Invalid Offsets Length", func(t *testing.T) {
		flatData := []byte{1, 2, 3, 4, 5}
		result := ReconstructByteArrays(flatData, []int{0, 5, 2}) // Odd length
		if len(result) != 0 {
			t.Errorf("Expected empty result for odd offsets length, got %d elements", len(result))
		}
	})

	t.Run("Out of Bounds Offsets", func(t *testing.T) {
		flatData := []byte{1, 2, 3, 4, 5}
		offsets := []int{0, 3, 3, 5} // Second entry is out of bounds
		result := ReconstructByteArrays(flatData, offsets)

		if len(result) != 2 {
			t.Fatalf("Expected 2 elements, got %d", len(result))
		}

		if len(result[0]) != 3 {
			t.Errorf("First element should have length 3, got %d", len(result[0]))
		}

		if len(result[1]) != 0 {
			t.Errorf("Second element should be empty due to bounds check, got length %d", len(result[1]))
		}
	})

	t.Run("Negative Offsets", func(t *testing.T) {
		flatData := []byte{1, 2, 3, 4, 5}
		offsets := []int{0, 3, -1, 2} // Negative start offset
		result := ReconstructByteArrays(flatData, offsets)

		if len(result) != 2 {
			t.Fatalf("Expected 2 elements, got %d", len(result))
		}

		if len(result[1]) != 0 {
			t.Errorf("Second element should be empty due to negative offset, got length %d", len(result[1]))
		}
	})
}

// TestOrderIntegrity verifies packet order and content integrity are perfectly maintained
func TestOrderIntegrity(t *testing.T) {
	// Define test sizes - includes both easy and challenging cases
	testSizes := []struct {
		name       string
		count      int
		maxWorkers int
	}{
		{"Small", 1000, 8},
		{"Medium", 100_000, 16},
		{"Large", 1_000_000, 32},
	}

	// Save original worker count to restore later
	originalWorkerCount := GetUtilWorkers()
	defer SetUtilWorkers(originalWorkerCount)

	for _, tc := range testSizes {
		t.Run(tc.name, func(t *testing.T) {
			// Create deterministically patterned test data with encoded positions
			arrays := make([][]byte, tc.count)
			totalSize := 0

			// Each array has a size based on its position (for easier debugging)
			// and contains its index encoded in the data
			for i := 0; i < tc.count; i++ {
				// Create a unique size pattern based on position
				// This helps detect if arrays get mixed up
				size := 20 + (i % 13)

				// Create data with position-based pattern
				data := make([]byte, size)

				// Encode the array index in the first 4 bytes
				// This ensures we can detect any reordering
				data[0] = byte((i >> 24) & 0xFF)
				data[1] = byte((i >> 16) & 0xFF)
				data[2] = byte((i >> 8) & 0xFF)
				data[3] = byte(i & 0xFF)

				// Fill the rest with a deterministic but position-dependent pattern
				for j := 4; j < size; j++ {
					data[j] = byte((i * j) & 0xFF)
				}

				arrays[i] = data
				totalSize += size
			}

			// Create flattened representation
			flatData := make([]byte, totalSize)
			offsets := make([]int, tc.count*2)

			position := 0
			for i, arr := range arrays {
				offsets[i*2] = position
				offsets[i*2+1] = len(arr)
				copy(flatData[position:], arr)
				position += len(arr)
			}

			// First test: Verify that our test can detect corruption
			// This is a "test of the test" to ensure our validation logic works
			t.Run("ValidateTestDetection", func(t *testing.T) {
				// Use a clean copy of the flattened data
				corruptFlatData := make([]byte, len(flatData))
				copy(corruptFlatData, flatData)

				// Deliberately corrupt a byte in the middle of the data
				corruptPos := len(corruptFlatData) / 2
				corruptFlatData[corruptPos] = corruptFlatData[corruptPos] ^ 0xFF // Flip all bits

				// Reconstruct with the corrupted data
				reconstructed := ReconstructByteArrays(corruptFlatData, offsets)

				// Our validation code should detect this corruption
				errorFound := false
				for i := 0; i < tc.count && !errorFound; i++ {
					result := reconstructed[i]
					if len(result) < 4 {
						continue
					}

					encodedIndex := (int(result[0]) << 24) |
						(int(result[1]) << 16) |
						(int(result[2]) << 8) |
						int(result[3])

					// Skip arrays with wrong length
					if len(result) != len(arrays[i]) {
						errorFound = true
						break
					}

					// Skip arrays with wrong index
					if encodedIndex != i {
						errorFound = true
						break
					}

					// Check for content corruption
					for j := 4; j < len(result); j++ {
						expected := byte((i * j) & 0xFF)
						if result[j] != expected {
							errorFound = true
							break
						}
					}
				}

				// The test SHOULD find an error with our corrupted data
				if !errorFound {
					t.Errorf("Validation failure: Test did not detect deliberately corrupted data")
				} else {
					t.Logf("Corruption detection validated successfully")
				}
			})

			// Test with different worker counts
			workerCounts := []int{1, 2, 4, tc.maxWorkers}

			for _, workers := range workerCounts {
				SetUtilWorkers(workers)

				t.Logf("Testing with %d workers...", workers)

				// Reconstruct the arrays
				start := time.Now()
				reconstructed := ReconstructByteArrays(flatData, offsets)
				elapsed := time.Since(start)

				// Verify length
				if len(reconstructed) != tc.count {
					t.Fatalf("Worker count %d: Length mismatch - expected %d arrays, got %d",
						workers, tc.count, len(reconstructed))
				}

				// Verify order and content of each array
				errorCount := 0
				for i := 0; i < tc.count; i++ {
					original := arrays[i]
					result := reconstructed[i]

					// Verify length
					if len(result) != len(original) {
						errorCount++
						if errorCount <= 5 {
							t.Errorf("Worker count %d: Size mismatch at position %d - expected %d bytes, got %d bytes",
								workers, i, len(original), len(result))
						}
						continue
					}

					// Extract the encoded index
					encodedIndex := (int(result[0]) << 24) |
						(int(result[1]) << 16) |
						(int(result[2]) << 8) |
						int(result[3])

					// Verify the encoded index matches the array position
					if encodedIndex != i {
						errorCount++
						if errorCount <= 5 {
							t.Errorf("Worker count %d: Order violation at position %d - found array with encoded index %d",
								workers, i, encodedIndex)
						}
						continue
					}

					// Verify content
					for j := 4; j < len(result); j++ {
						expected := byte((i * j) & 0xFF)
						if result[j] != expected {
							errorCount++
							if errorCount <= 5 {
								t.Errorf("Worker count %d: Content corruption at position %d, byte %d - expected %d, got %d",
									workers, i, j, expected, result[j])
							}
							break
						}
					}
				}

				if errorCount > 0 {
					t.Fatalf("Worker count %d: Found %d errors in reconstructed data",
						workers, errorCount)
				}

				// Log performance metrics
				t.Logf("Worker count %d: Processed %d arrays in %v (%.2f arrays/sec, %.2f MB/sec)",
					workers, tc.count, elapsed,
					float64(tc.count)/elapsed.Seconds(),
					float64(totalSize)/(1024*1024)/elapsed.Seconds())

				// Help GC between tests
				reconstructed = nil
				runtime.GC()
			}
		})
	}
}

func BenchmarkReconstructByteArrays(b *testing.B) {
	// Create different sized test datasets
	benchCases := []struct {
		name  string
		count int
		size  int
	}{
		{"Small", 100, 20},
		{"Medium", 10_000, 100},
		{"Large", 100_000, 1500},
		{"Huge", 1_000_000, 60},
		{"Massive", 40_000_000, 60},
	}

	for _, bc := range benchCases {
		b.Run(bc.name, func(b *testing.B) {
			// Create test data once
			original := make([][]byte, bc.count)
			totalSize := 0

			// Generate data
			for i := 0; i < bc.count; i++ {
				original[i] = make([]byte, bc.size)
				for j := 0; j < bc.size; j++ {
					original[i][j] = byte((i + j) % 256)
				}
				totalSize += bc.size
			}

			// Flatten data
			flatData := make([]byte, totalSize)
			offsets := make([]int, bc.count*2)
			pos := 0

			for i, arr := range original {
				offsets[i*2] = pos
				offsets[i*2+1] = len(arr)
				copy(flatData[pos:], arr)
				pos += len(arr)
			}

			// Reset timer before the actual benchmark
			b.ResetTimer()

			// Log additional information
			b.ReportAllocs()

			// Run benchmark
			for i := 0; i < b.N; i++ {
				result := ReconstructByteArrays(flatData, offsets)

				// Make sure the result is used to prevent optimization
				if len(result) != bc.count {
					b.Fatalf("Invalid result length: %d", len(result))
				}

				// Help GC between iterations for large datasets
				if bc.count >= 100000 {
					runtime.GC()
				}
			}
		})
	}
}

// TestParallelismEfficiency tests how well the function scales with more workers
func TestParallelismEfficiency(t *testing.T) {
	if testing.Short() {
		t.Skip("Skipping parallelism efficiency test in short mode")
	}

	// Define different size test cases
	testCases := []struct {
		name  string
		count int
		size  int
	}{
		{"SmallPayloads", 5_000_000, 10},  // Many small payloads
		{"MediumPayloads", 1_000_000, 60}, // Original test case
		{"LargePayloads", 200_000, 1450},  // Fewer but larger payloads
		{"MixedLoad", 500_000, 120},       // Balanced case
		{"Huge", 10_000_000, 60},          // Extreme small payload case
	}

	// Test different worker counts
	workerConfigs := []int{1, 2, 4, 8, runtime.NumCPU()}
	if runtime.NumCPU() > 16 {
		workerConfigs = append(workerConfigs, 16, runtime.NumCPU()*2)
	}

	// Save the original worker count to restore later
	originalWorkerCount := GetUtilWorkers()
	defer SetUtilWorkers(originalWorkerCount) // Restore at the end

	// Process each test case
	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			// Generate data for this test case
			totalSize := tc.count * tc.size
			flatData := make([]byte, totalSize)
			offsets := make([]int, tc.count*2)

			// Fill the flat data and offsets arrays directly
			for i := 0; i < tc.count; i++ {
				start := i * tc.size
				offsets[i*2] = start
				offsets[i*2+1] = tc.size

				// Fill with deterministic pattern
				for j := 0; j < tc.size; j++ {
					flatData[start+j] = byte((i + j) % 256)
				}
			}

			results := make(map[int]time.Duration)

			// Test each worker configuration
			for _, workers := range workerConfigs {
				// Set the worker count for this test run
				SetUtilWorkers(workers)

				// Run 3 times and take the best result
				var bestTime time.Duration = 1<<63 - 1 // Max duration
				for i := 0; i < 3; i++ {
					start := time.Now()
					result := ReconstructByteArrays(flatData, offsets)
					elapsed := time.Since(start)

					if len(result) != tc.count {
						t.Fatalf("Invalid result length with %d workers: %d", workers, len(result))
					}

					if elapsed < bestTime {
						bestTime = elapsed
					}

					// Force GC between runs
					result = nil
					runtime.GC()
				}

				results[workers] = bestTime
				t.Logf("%s - Workers: %d, Time: %v, Arrays/sec: %.2f, MB/sec: %.2f",
					tc.name, workers, bestTime,
					float64(tc.count)/bestTime.Seconds(),
					float64(totalSize)/(1024*1024)/bestTime.Seconds())
			}

			// Report speedup for this test case
			if baseline, ok := results[1]; ok {
				t.Logf("--- %s Parallelism Efficiency ---", tc.name)
				for workers, duration := range results {
					if workers == 1 {
						continue
					}
					speedup := float64(baseline) / float64(duration)
					efficiency := speedup / float64(workers) * 100
					t.Logf("  Speedup with %d workers: %.2fx (%.1f%% efficiency)",
						workers, speedup, efficiency)
				}
			}
		})
	}
}
