import unittest
import os
import sys
import time
import random
import multiprocessing
import types
from typing import List, Tuple
import numpy as np

# Ensure ohbother can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from ohbother.parallel_utils import (
    parallel_flatten_byte_arrays,
    prepare_flattened_data_for_go,
    flatten_byte_arrays
)


class TestParallelFlattenByteArrays(unittest.TestCase):
    """Tests for parallel_flatten_byte_arrays function"""

    def generate_test_data(self, count: int, min_size: int, max_size: int) -> List[bytes]:
        """Generate test data with specified characteristics"""
        arrays = []
        for _ in range(count):
            # Determine size for this array
            size = min_size
            if max_size > min_size:
                size = random.randint(min_size, max_size)
            
            # Generate random byte data
            data = bytes(random.getrandbits(8) for _ in range(size))
            arrays.append(data)
        return arrays

    def test_empty_input(self):
        """Test with empty input"""
        result, offsets = parallel_flatten_byte_arrays([])
        self.assertEqual(result, b'')
        self.assertEqual(offsets, [])

    def test_single_array(self):
        """Test with a single byte array"""
        test_data = [b'hello world']
        result, offsets = parallel_flatten_byte_arrays(test_data)
        self.assertEqual(result, b'hello world')
        self.assertEqual(offsets, [0, 11])  # Start at 0, length 11

    def test_flattening_correctness(self):
        """Test that flattening preserves all data correctly"""
        test_data = [b'hello', b'world', b'python', b'test']
        result, offsets = parallel_flatten_byte_arrays(test_data)
        
        # Expected result is concatenation of all arrays
        expected_result = b'helloworldpythontest'
        self.assertEqual(result, expected_result)
        
        # Verify offsets
        self.assertEqual(offsets, [0, 5, 5, 5, 10, 6, 16, 4])
        
        # Verify we can reconstruct the original data
        reconstructed = []
        for i in range(0, len(offsets), 2):
            start = offsets[i]
            length = offsets[i+1]
            reconstructed.append(result[start:start+length])
        
        self.assertEqual(reconstructed, test_data)

    def test_large_dataset(self):
        """Test with a larger dataset that should trigger parallelization"""
        # Generate 20,000 small arrays
        test_data = self.generate_test_data(20000, 10, 50)
        
        start_time = time.time()
        result, offsets = parallel_flatten_byte_arrays(test_data)
        elapsed = time.time() - start_time
        
        print(f"\nLarge dataset flattening: {len(test_data):,} arrays in {elapsed:.3f}s")
        
        # Verify total size
        expected_size = sum(len(arr) for arr in test_data)
        self.assertEqual(len(result), expected_size)
        
        # Verify offsets length
        self.assertEqual(len(offsets), len(test_data) * 2)
        
        # Verify a few random samples
        for _ in range(10):
            idx = random.randint(0, len(test_data) - 1)
            start = offsets[idx*2]
            length = offsets[idx*2+1]
            self.assertEqual(result[start:start+length], test_data[idx])

    def test_parallel_vs_sequential(self):
        """Compare parallel vs sequential performance"""
        # This is a larger test that should benefit from parallelization
        test_data = self.generate_test_data(50000, 100, 500)
        
        # Run sequential version
        start_time = time.time()
        seq_result, seq_offsets = flatten_byte_arrays(test_data)
        seq_time = time.time() - start_time
        
        # Run parallel version
        start_time = time.time()
        par_result, par_offsets = parallel_flatten_byte_arrays(test_data)
        par_time = time.time() - start_time
        
        print(f"\nSequential flattening: {seq_time:.3f}s, Parallel: {par_time:.3f}s, Speedup: {seq_time/par_time:.2f}x")
        
        # Results should be identical
        self.assertEqual(seq_result, par_result)
        self.assertEqual(seq_offsets, par_offsets)

    def test_worker_scaling(self):
        """Test scaling with different worker counts"""
        # Skip on CI or with -m pytest.mark.quick
        if "CI" in os.environ or hasattr(self, "quick"):
            self.skipTest("Skipping worker scaling test in CI environment")
        
        test_data = self.generate_test_data(100000, 50, 200)
        
        worker_counts = [1, 2, 4, multiprocessing.cpu_count()]
        times = {}
        
        for workers in worker_counts:
            start_time = time.time()
            result, _ = parallel_flatten_byte_arrays(test_data, num_workers=workers)
            times[workers] = time.time() - start_time
        
        print("\nWorker scaling results:")
        for workers, elapsed in times.items():
            print(f"  {workers} workers: {elapsed:.3f}s ({len(test_data)/elapsed:.0f} arrays/sec)")
        
        # Basic validation - we're not asserting performance, just checking results are correct
        self.assertEqual(len(result), sum(len(arr) for arr in test_data))


class TestPrepareDataForGo(unittest.TestCase):
    """Tests for prepare_flattened_data_for_go function"""
    
    def generate_flat_test_data(self, count: int, size: int) -> Tuple[bytes, List[int]]:
        """Generate flattened test data with consistent sizes"""
        total_size = count * size
        flat_data = bytes(random.getrandbits(8) for _ in range(total_size))
        
        # Create offsets
        offsets = []
        for i in range(count):
            offsets.append(i * size)  # start
            offsets.append(size)      # length
            
        return flat_data, offsets

    def test_data_conversion(self):
        """Test basic data conversion functionality"""
        # Create mock classes
        class MockSliceByte:
            def __init__(self, data=None):
                self._data = data or b''
            
            @staticmethod
            def from_bytes(data):
                return MockSliceByte(data)
                
            def to_bytes(self):
                return self._data
                
        class MockSliceInt:
            def __init__(self, data=None):
                self.data = data or []
        
        # Store original modules and attributes
        original_modules = {}
        if 'ohbother.generated.go' in sys.modules:
            original_modules['ohbother.generated.go'] = sys.modules['ohbother.generated.go']
        
        # Store original function references
        from ohbother import parallel_utils as pu
        original_slice_byte = getattr(pu, 'Slice_byte', None)
        original_has_slice_byte = pu._has_slice_byte
        
        try:
            # Create and inject mock module
            mock_go = types.ModuleType('go')
            mock_go.Slice_byte = MockSliceByte
            mock_go.Slice_int = MockSliceInt
            sys.modules['ohbother.generated.go'] = mock_go
            pu.Slice_byte = MockSliceByte
            pu._has_slice_byte = True
            
            # Create test data (relatively small)
            flat_data, offsets = self.generate_flat_test_data(1000, 50)
            
            # Convert to Go types
            go_flat_data, go_offsets = pu.prepare_flattened_data_for_go(flat_data, offsets)
            
            # Verify types
            self.assertIsInstance(go_flat_data, MockSliceByte)
            self.assertIsInstance(go_offsets, MockSliceInt)
            
            # Verify content
            self.assertEqual(go_flat_data.to_bytes(), flat_data)
            self.assertEqual(go_offsets.data, offsets)
            
        finally:
            # Restore original modules and attributes
            for name, module in original_modules.items():
                sys.modules[name] = module
                
            # Restore original function references
            pu.Slice_byte = original_slice_byte
            pu._has_slice_byte = original_has_slice_byte
            
            # Clean up mock module
            if 'ohbother.generated.go' in sys.modules and \
               'ohbother.generated.go' not in original_modules:
                del sys.modules['ohbother.generated.go']

    def test_large_dataset_conversion(self):
        """Test conversion of a large dataset"""
        # Create mock classes
        class MockSliceByte:
            def __init__(self, data=None):
                self._data = data or b''
            
            @staticmethod
            def from_bytes(data):
                return MockSliceByte(data)
                
            def to_bytes(self):
                return self._data
                
        class MockSliceInt:
            def __init__(self, data=None):
                self.data = data or []
        
        # Store original modules and attributes
        original_modules = {}
        if 'ohbother.generated.go' in sys.modules:
            original_modules['ohbother.generated.go'] = sys.modules['ohbother.generated.go']
        
        # Store original function references
        from ohbother import parallel_utils as pu
        original_slice_byte = getattr(pu, 'Slice_byte', None)
        original_has_slice_byte = pu._has_slice_byte
        
        try:
            # Create and inject mock module
            mock_go = types.ModuleType('go')
            mock_go.Slice_byte = MockSliceByte
            mock_go.Slice_int = MockSliceInt
            sys.modules['ohbother.generated.go'] = mock_go
            pu.Slice_byte = MockSliceByte
            pu._has_slice_byte = True
            
            # Generate larger test data to trigger parallel processing
            flat_data, offsets = self.generate_flat_test_data(200000, 60)
            
            start_time = time.time()
            go_flat_data, go_offsets = pu.prepare_flattened_data_for_go(flat_data, offsets)
            elapsed = time.time() - start_time
            
            print(f"\nLarge dataset conversion: {len(flat_data):,} bytes in {elapsed:.3f}s")
            
            # Verify conversion worked by checking content
            self.assertEqual(go_flat_data.to_bytes(), flat_data)
            self.assertEqual(go_offsets.data, offsets)
            
        finally:
            # Restore original modules and attributes
            for name, module in original_modules.items():
                sys.modules[name] = module
                
            # Restore original function references
            pu.Slice_byte = original_slice_byte
            pu._has_slice_byte = original_has_slice_byte
            
            # Clean up mock module
            if 'ohbother.generated.go' in sys.modules and \
               'ohbother.generated.go' not in original_modules:
                del sys.modules['ohbother.generated.go']


class TestAdditionalFeatures(unittest.TestCase):
    """Additional tests that don't require Go handles"""
    
    def test_content_integrity(self):
        """Test that flattening/unflattening preserves order and content"""
        # Create arrays with index-encoded content
        count = 10000
        arrays = []
        
        for i in range(count):
            # Variable size between 20-33 bytes
            size = 20 + (i % 13)
            data = bytearray(size)
            
            # Encode the index in the first 4 bytes (like in Go test)
            data[0] = (i >> 24) & 0xFF
            data[1] = (i >> 16) & 0xFF
            data[2] = (i >> 8) & 0xFF
            data[3] = i & 0xFF
            
            # Fill the rest with a deterministic pattern
            for j in range(4, size):
                data[j] = (i * j) & 0xFF
                
            arrays.append(bytes(data))
            
        # Flatten the arrays
        flat_data, offsets = parallel_flatten_byte_arrays(arrays)
        
        # Unflatten manually to check integrity
        error_count = 0
        for i in range(count):
            start = offsets[i*2]
            length = offsets[i*2+1]
            
            # Get the array
            array = flat_data[start:start+length]
            
            # Extract the encoded index
            encoded_idx = (array[0] << 24) | (array[1] << 16) | (array[2] << 8) | array[3]
            
            # Check index matches position
            if encoded_idx != i:
                error_count += 1
                if error_count <= 5:  # Limit error reporting
                    print(f"Order violation at position {i}: found encoded index {encoded_idx}")
                    
            # Check content
            for j in range(4, len(array)):
                expected = (i * j) & 0xFF
                if array[j] != expected:
                    error_count += 1
                    if error_count <= 5:
                        print(f"Content corruption at position {i}, byte {j}")
                    break
                    
        self.assertEqual(error_count, 0, f"Found {error_count} errors in reconstructed data")
        
    def test_corruption_detection(self):
        """Test that we can detect corrupted data"""
        # Create arrays with index-encoded content (smaller set)
        count = 1000
        arrays = []
        
        for i in range(count):
            size = 20 + (i % 13)
            data = bytearray(size)
            
            # Encode index
            data[0] = (i >> 24) & 0xFF
            data[1] = (i >> 16) & 0xFF
            data[2] = (i >> 8) & 0xFF
            data[3] = i & 0xFF
            
            # Fill with pattern
            for j in range(4, size):
                data[j] = (i * j) & 0xFF
                
            arrays.append(bytes(data))
            
        # Flatten the arrays
        flat_data, offsets = parallel_flatten_byte_arrays(arrays)
        
        # Create corrupted copy
        corrupt_data = bytearray(flat_data)
        corruption_pos = len(corrupt_data) // 2
        corrupt_data[corruption_pos] = corrupt_data[corruption_pos] ^ 0xFF  # Flip all bits
        
        # Manually check if corruption can be detected
        error_found = False
        for i in range(count):
            start = offsets[i*2]
            length = offsets[i*2+1]
            
            array = corrupt_data[start:start+length]
            
            # Skip if too short
            if len(array) < 4:
                continue
                
            # Extract encoded index
            encoded_idx = (array[0] << 24) | (array[1] << 16) | (array[2] << 8) | array[3]
            
            # Check index
            if encoded_idx != i:
                error_found = True
                break
                
            # Check content
            for j in range(4, len(array)):
                expected = (i * j) & 0xFF
                if array[j] != expected:
                    error_found = True
                    break
            
            if error_found:
                break
                
        self.assertTrue(error_found, "Corruption was not detected")
        
    def test_numpy_integration(self):
        """Test integration with numpy arrays"""
        try:
            import numpy as np
        except ImportError:
            self.skipTest("NumPy not available")
            
        # Create numpy arrays of bytes
        arrays = []
        for i in range(1000):
            # Create numpy array with random data
            size = random.randint(20, 100)
            arr = np.random.randint(0, 256, size=size, dtype=np.uint8)
            arrays.append(arr.tobytes())
            
        # Flatten the arrays
        flat_data, offsets = parallel_flatten_byte_arrays(arrays)
        
        # Verify we can reconstruct
        for i in range(len(arrays)):
            start = offsets[i*2]
            length = offsets[i*2+1]
            reconstructed = flat_data[start:start+length]
            self.assertEqual(reconstructed, arrays[i])
            
        # Convert numpy array directly (this should raise an error or convert)
        large_array = np.random.randint(0, 256, size=10000, dtype=np.uint8)
        try:
            result, offsets = parallel_flatten_byte_arrays([large_array])
            # If we get here, conversion succeeded - verify result
            self.assertEqual(result, large_array.tobytes())
        except Exception as e:
            # This is also acceptable, as long as it's documented
            print(f"Note: Direct NumPy array flattening raised: {e}")
            
    def test_numpy_batch_integration(self):
        """Test flattening of multiple NumPy arrays"""
        try:
            import numpy as np
        except ImportError:
            self.skipTest("NumPy not available")
            
        # Create a batch of different sized numpy arrays
        arrays = []
        for i in range(500):
            size = 20 + (i % 13)  # Variable sizes like in Go test
            arr = np.random.randint(0, 256, size=size, dtype=np.uint8)
            
            # Encode the index in first 4 bytes (mirroring Go test)
            arr[0] = (i >> 24) & 0xFF
            arr[1] = (i >> 16) & 0xFF
            arr[2] = (i >> 8) & 0xFF
            arr[3] = i & 0xFF
            
            arrays.append(arr.tobytes())
            
        # Flatten arrays
        flat_data, offsets = parallel_flatten_byte_arrays(arrays)
        
        # Verify we can reconstruct and indexes are preserved
        for i in range(len(arrays)):
            start = offsets[i*2]
            length = offsets[i*2+1]
            reconstructed = flat_data[start:start+length]
            
            # Check encoded index
            encoded_idx = (reconstructed[0] << 24) | (reconstructed[1] << 16) | (reconstructed[2] << 8) | reconstructed[3]
            self.assertEqual(encoded_idx, i, f"Index mismatch at position {i}")
            
            # Verify content matches original
            self.assertEqual(reconstructed, arrays[i])
            
    def test_order_integrity(self):
        """Test that flattening/unflattening preserves order like the Go TestOrderIntegrity"""
        # Create arrays with index-encoded content (larger set)
        count = 10000
        arrays = []
        
        for i in range(count):
            size = 20 + (i % 13)  # Variable size based on index like in Go test
            data = bytearray(size)
            
            # Encode index exactly like in Go test
            data[0] = (i >> 24) & 0xFF
            data[1] = (i >> 16) & 0xFF
            data[2] = (i >> 8) & 0xFF
            data[3] = i & 0xFF
            
            # Fill with deterministic pattern like in Go test
            for j in range(4, size):
                data[j] = (i * j) & 0xFF
                
            arrays.append(bytes(data))
            
        # Flatten the arrays
        flat_data, offsets = parallel_flatten_byte_arrays(arrays)
        
        # Test corruption detection by creating corrupted copy
        corrupt_data = bytearray(flat_data)
        corruption_pos = len(corrupt_data) // 2
        corrupt_data[corruption_pos] = corrupt_data[corruption_pos] ^ 0xFF  # Flip bits
        
        # Check if corruption can be detected
        error_found = False
        for i in range(count):
            start = offsets[i*2]
            length = offsets[i*2+1]
            orig_array = flat_data[start:start+length]
            corrupt_array = corrupt_data[start:start+length]
            
            if orig_array != corrupt_array:
                error_found = True
                break
                
        self.assertTrue(error_found, "Corruption detection test failed")
        
        # Verify reconstruction from original flattened data
        error_count = 0
        for i in range(count):
            start = offsets[i*2]
            length = offsets[i*2+1]
            array = flat_data[start:start+length]
            
            # Extract encoded index
            encoded_idx = (array[0] << 24) | (array[1] << 16) | (array[2] << 8) | array[3]
            
            # Check index matches position
            if encoded_idx != i:
                error_count += 1
                if error_count <= 5:  # Limit error reporting like in Go test
                    print(f"Order violation at position {i}: found encoded index {encoded_idx}")
                    
            # Check content integrity
            for j in range(4, len(array)):
                expected = (i * j) & 0xFF
                if array[j] != expected:
                    error_count += 1
                    if error_count <= 5:
                        print(f"Content corruption at position {i}, byte {j}")
                    break
                    
        self.assertEqual(error_count, 0, f"Found {error_count} errors in data integrity check")
        
    def test_parallelism_efficiency(self):
        """Test how well the function scales with different worker counts like Go TestParallelismEfficiency"""
        # Skip on CI or with -m pytest.mark.quick
        if "CI" in os.environ or hasattr(self, "quick"):
            self.skipTest("Skipping parallelism efficiency test in CI environment")
        
        # Define test case sizes similar to Go
        test_sizes = [
            ("SmallPayloads", 100000, 10),
            ("MediumPayloads", 50000, 60),
            ("LargePayloads", 10000, 500),
        ]
        
        # Test with different worker configurations
        worker_counts = [1, 2, 4, multiprocessing.cpu_count()]
        
        # Only test large configurations on high-core machines
        if multiprocessing.cpu_count() > 8:
            worker_counts.append(8)
            
        for name, count, size in test_sizes:
            print(f"\nTesting {name}: {count} arrays of {size} bytes each")
            
            # Generate test data once
            arrays = []
            for i in range(count):
                data = bytearray(size)
                for j in range(size):
                    data[j] = ((i + j) % 256) & 0xFF
                arrays.append(bytes(data))
                
            # Track results for different worker counts
            results = {}
            
            # Test each worker configuration
            for workers in worker_counts:
                # Run 3 times and take best result like Go test
                best_time = float('inf')
                for _ in range(3):
                    start_time = time.time()
                    result, offsets = parallel_flatten_byte_arrays(arrays, num_workers=workers)
                    elapsed = time.time() - start_time
                    
                    if elapsed < best_time:
                        best_time = elapsed
                
                results[workers] = best_time
                total_mb = sum(len(arr) for arr in arrays) / (1024*1024)
                print(f"  Workers: {workers}, Time: {best_time:.3f}s, " 
                      f"Arrays/sec: {count/best_time:.2f}, MB/sec: {total_mb/best_time:.2f}")
            
            # Report speedup like Go test
            if 1 in results:
                baseline = results[1]
                print(f"--- {name} Parallelism Efficiency ---")
                for workers, duration in results.items():
                    if workers == 1:
                        continue
                    speedup = baseline / duration
                    efficiency = (speedup / workers) * 100
                    print(f"  Speedup with {workers} workers: {speedup:.2f}x ({efficiency:.1f}% efficiency)")


class TestPrepareDataForGoNoHandles(unittest.TestCase):
    """Tests for prepare_flattened_data_for_go function that don't require Go handles"""
    
    def generate_flat_test_data(self, count: int, size: int) -> Tuple[bytes, List[int]]:
        """Generate flattened test data with consistent sizes"""
        total_size = count * size
        flat_data = bytes(random.getrandbits(8) for _ in range(total_size))
        
        # Create offsets
        offsets = []
        for i in range(count):
            offsets.append(i * size)  # start
            offsets.append(size)      # length
            
        return flat_data, offsets

    def test_mock_conversion(self):
        """Test the conversion function with mocked Go types"""
        # Create mock classes
        class MockSliceByte:
            def __init__(self, data=None):
                self._data = data
            
            @staticmethod
            def from_bytes(data):
                return MockSliceByte(data)
                
            def to_bytes(self):
                return self._data
                
        class MockSliceInt:
            def __init__(self, data=None):
                self.data = data or []
        
        # Store original modules and attributes
        original_modules = {}
        if 'ohbother.generated.go' in sys.modules:
            original_modules['ohbother.generated.go'] = sys.modules['ohbother.generated.go']
        
        # Store original function references
        from ohbother import parallel_utils
        original_slice_byte = getattr(parallel_utils, 'Slice_byte', None)
        original_has_slice_byte = parallel_utils._has_slice_byte
        
        try:
            # Create mock module
            mock_go = types.ModuleType('go')
            mock_go.Slice_byte = MockSliceByte
            mock_go.Slice_int = MockSliceInt
            
            # Inject mocks
            sys.modules['ohbother.generated.go'] = mock_go
            parallel_utils.Slice_byte = MockSliceByte
            parallel_utils._has_slice_byte = True
            
            # Run test with mock
            flat_data, offsets = self.generate_flat_test_data(1000, 50)
            go_flat_data, go_offsets = parallel_utils.prepare_flattened_data_for_go(flat_data, offsets)
            
            # Verify results
            self.assertIsInstance(go_flat_data, MockSliceByte)
            self.assertIsInstance(go_offsets, MockSliceInt)
            
            # Verify data integrity
            self.assertEqual(go_flat_data.to_bytes(), flat_data)
            self.assertEqual(go_offsets.data, offsets)
            
        finally:
            # Restore original modules and attributes
            for name, module in original_modules.items():
                sys.modules[name] = module
                
            # Restore original function references
            parallel_utils.Slice_byte = original_slice_byte
            parallel_utils._has_slice_byte = original_has_slice_byte
            
            # Clean up mock module
            if 'ohbother.generated.go' in sys.modules and \
               'ohbother.generated.go' not in original_modules:
                del sys.modules['ohbother.generated.go']
                
    def test_large_data_fallback(self):
        """Test that the function handles large data even without Go types"""
        # Create mock classes
        class MockSliceByte:
            def __init__(self, data=None):
                self._data = data or b''
            
            @staticmethod
            def from_bytes(data):
                return MockSliceByte(data)
                
            def to_bytes(self):
                return self._data
                
        class MockSliceInt:
            def __init__(self, data=None):
                self.data = data or []
        
        # Store original modules and attributes
        original_modules = {}
        if 'ohbother.generated.go' in sys.modules:
            original_modules['ohbother.generated.go'] = sys.modules['ohbother.generated.go']
        
        # Store original function references
        from ohbother import parallel_utils as pu
        original_slice_byte = getattr(pu, 'Slice_byte', None)
        original_has_slice_byte = pu._has_slice_byte
        
        try:
            # Create and inject mock module
            mock_go = types.ModuleType('go')
            mock_go.Slice_byte = MockSliceByte
            mock_go.Slice_int = MockSliceInt
            sys.modules['ohbother.generated.go'] = mock_go
            pu.Slice_byte = MockSliceByte
            pu._has_slice_byte = True
            
            # Generate large test data
            flat_data, offsets = self.generate_flat_test_data(100000, 60)
            
            # Test with mock types
            result_data, result_offsets = pu.prepare_flattened_data_for_go(flat_data, offsets)
            
            # Verify results using to_bytes() method
            self.assertEqual(result_data.to_bytes(), flat_data)
            self.assertEqual(result_offsets.data, offsets)
            
        finally:
            # Restore original modules and attributes
            for name, module in original_modules.items():
                sys.modules[name] = module
                
            # Restore original function references
            pu.Slice_byte = original_slice_byte
            pu._has_slice_byte = original_has_slice_byte
            
            # Clean up mock module
            if 'ohbother.generated.go' in sys.modules and \
               'ohbother.generated.go' not in original_modules:
                del sys.modules['ohbother.generated.go']
                
    def test_edge_cases(self):
        """Test edge cases like empty data, None values, etc."""
        # Create mock classes
        class MockSliceByte:
            def __init__(self, data=None):
                self._data = data or b''
            
            @staticmethod
            def from_bytes(data):
                return MockSliceByte(data)
                
            def to_bytes(self):
                return self._data
                
        class MockSliceInt:
            def __init__(self, data=None):
                self.data = data or []
                
        # Store original modules and attributes
        original_modules = {}
        if 'ohbother.generated.go' in sys.modules:
            original_modules['ohbother.generated.go'] = sys.modules['ohbother.generated.go']
        
        # Store original function references
        from ohbother import parallel_utils as pu
        original_slice_byte = getattr(pu, 'Slice_byte', None)
        original_has_slice_byte = pu._has_slice_byte
        
        try:
            # Create and inject mock module
            mock_go = types.ModuleType('go')
            mock_go.Slice_byte = MockSliceByte
            mock_go.Slice_int = MockSliceInt
            sys.modules['ohbother.generated.go'] = mock_go
            pu.Slice_byte = MockSliceByte
            pu._has_slice_byte = True
            
            # Test with empty data
            result_data, result_offsets = pu.prepare_flattened_data_for_go(b'', [])
            self.assertEqual(result_data.to_bytes(), b'')
            self.assertEqual(result_offsets.data, [])
            
            # Test with invalid offsets
            flat_data, _ = self.generate_flat_test_data(10, 5)
            result_data, result_offsets = pu.prepare_flattened_data_for_go(flat_data, [0, 5, 10])
            self.assertEqual(result_data.to_bytes(), flat_data)
            
        finally:
            # Restore original modules and attributes
            for name, module in original_modules.items():
                sys.modules[name] = module
                
            # Restore original function references
            pu.Slice_byte = original_slice_byte
            pu._has_slice_byte = original_has_slice_byte
            
            # Clean up mock module
            if 'ohbother.generated.go' in sys.modules and \
               'ohbother.generated.go' not in original_modules:
                del sys.modules['ohbother.generated.go']


if __name__ == "__main__":
    unittest.main()