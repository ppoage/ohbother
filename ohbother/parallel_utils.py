"""
High-performance parallel utilities for converting between Python and Go data types.

This module provides optimized functions for converting large numbers of Python
byte arrays to Go slices in parallel using both multiprocessing and Go's
native concurrency. It also includes utilities for flattening byte arrays for
efficient transfer across the Python-Go boundary.
"""

import multiprocessing
import os
import sys
import time
from typing import List, Union, Iterable, Any, Tuple
from functools import partial
import array

# Import required Go types - use try/except only for error cases
_has_slice_byte = False
_has_optimized = False
_has_indexed_convert = False

try:
    # Fast path - just try the main import locations
    try:
        from .generated.go import Slice_byte
        from .generated.ohbother import BatchConvertPythonBytesToSlices
        # Try to import the new indexed version
        try:
            from .generated.ohbother import BatchConvertIndexedBytesToSlices
            _has_indexed_convert = True
        except ImportError:
            _has_indexed_convert = False
        _has_slice_byte = True
        _has_optimized = True
    except ImportError:
        # Try alternative import paths
        from .generated.ohbother import Slice_byte
        from .generated.ohbother import BatchConvertPythonBytesToSlices
        # Try to import the new indexed version
        try:
            from .generated.ohbother import BatchConvertIndexedBytesToSlices
            _has_indexed_convert = True
        except ImportError:
            _has_indexed_convert = False
        _has_slice_byte = True
        _has_optimized = True
except ImportError:
    # Only print warnings if optimizations aren't available
    print("Warning: Optimized Go functions not available", file=sys.stderr, flush=True)
    
    # Create fallback implementation
    class Slice_byte:
        """Fallback implementation of Slice_byte when Go version is unavailable"""
        def __init__(self, handle=None):
            self.handle = handle
            self._data = None
        
        @staticmethod
        def from_bytes(data):
            """Create a Slice_byte from Python bytes"""
            result = Slice_byte()
            result._data = data
            return result
        
        def to_bytes(self):
            """Convert back to Python bytes"""
            if self._data is not None:
                return self._data
            return b''

def _process_chunk(chunk_id, chunk):
    """
    Process a chunk of payloads in a separate process.
    
    Args:
        chunk_id: Identifier for this chunk (for debugging)
        chunk: List of byte arrays to convert
        
    Returns:
        List of converted Slice_byte objects
    """
    start_time = time.perf_counter()
    
    # First, check if the optimized indexed path is available
    if _has_indexed_convert:
        try:
            # Convert Python list to a map of indices to byte arrays
            indexed_bytes = {}
            for i, item in enumerate(chunk):
                indexed_bytes[i] = item
            
            # Use optimized Go implementation with indexed bytes
            handles = BatchConvertIndexedBytesToSlices(indexed_bytes, 8)
            
            # Process the handles
            result = []
            for i, handle in enumerate(handles):
                if i < len(chunk) and handle != 0:  # Skip any zero handles (errors)
                    result.append(Slice_byte(handle))
            
            duration = time.perf_counter() - start_time
            print(f"Chunk {chunk_id}: Processed {len(chunk):,} items in {duration:.3f}s using indexed conversion", 
                  file=sys.stderr)
            return result
            
        except Exception as e:
            # Log the error and fall through to the next method
            print(f"Error in chunk {chunk_id} using indexed conversion, trying standard method: {e}", 
                  file=sys.stderr)
            # Continue to next method
    
    # Try the standard optimized path if indexed version failed or isn't available
    if _has_optimized:
        try:
            # Convert Python bytes to Go Slice_byte objects first
            go_bytes = [Slice_byte.from_bytes(item) for item in chunk]
            
            # Use standard optimized Go implementation with converted objects
            handles = BatchConvertPythonBytesToSlices(go_bytes, 8)
            
            # Process the handles
            result = []
            for i, handle in enumerate(handles):
                if isinstance(handle, int):
                    # This is what we expect - an integer handle
                    result.append(Slice_byte(handle))
                else:
                    # Unexpected type - fallback for this item only
                    print(f"Warning: Got {type(handle)} instead of int for handle at index {i}", 
                          file=sys.stderr)
                    result.append(Slice_byte.from_bytes(chunk[i]))
            
            duration = time.perf_counter() - start_time
            print(f"Chunk {chunk_id}: Processed {len(chunk):,} items in {duration:.3f}s using standard conversion", 
                  file=sys.stderr)
            return result
            
        except Exception as e:
            # Log the error and fall through to the fallback
            print(f"Error in chunk {chunk_id}, using fallback: {e}", file=sys.stderr)
            # Continue to fallback below
    
    # Fallback implementation - process each byte array individually using from_bytes
    try:
        # Clear any previous errors
        result = []
        for item in chunk:
            try:
                # Use the from_bytes static method
                slice_obj = Slice_byte.from_bytes(item)
                result.append(slice_obj)
            except Exception as item_err:
                print(f"Error converting item in fallback mode: {item_err}", file=sys.stderr)
                # Skip this item if conversion fails
        
        duration = time.perf_counter() - start_time
        print(f"Chunk {chunk_id}: Processed {len(result)}/{len(chunk)} items with fallback in {duration:.3f}s", 
              file=sys.stderr)
        return result
        
    except Exception as fallback_err:
        print(f"Fatal error in fallback for chunk {chunk_id}: {fallback_err}", file=sys.stderr)
        # Return empty list as last resort
        return []

def parallel_bytes_to_go(data_list, num_workers=None):
    """
    Converts a list of byte objects to Go byte slices in parallel.
    
    Args:
        data_list: List of byte arrays to convert
        num_workers: Number of Python processes to use (defaults to CPU count)
        
    Returns:
        List of converted Slice_byte objects
    """
    # Edge case: if data_list is not a list/tuple, assume a single payload
    if not isinstance(data_list, (list, tuple)):
        return Slice_byte.from_bytes(data_list)
    
    if not data_list:
        return []
    
    # For small datasets, do conversion in the current process
    if len(data_list) < 1000:
        if _has_indexed_convert:
            # Use indexed version for small datasets too
            indexed_bytes = {}
            for i, item in enumerate(data_list):
                indexed_bytes[i] = item
            handles = BatchConvertIndexedBytesToSlices(indexed_bytes, num_workers or os.cpu_count())
            return [Slice_byte(h) for h in handles[:len(data_list)] if h != 0]
        elif _has_optimized:
            # Convert Python bytes to Go Slice_byte objects first
            go_bytes = [Slice_byte.from_bytes(item) for item in data_list]
            handles = BatchConvertPythonBytesToSlices(go_bytes, num_workers or os.cpu_count())
            return [Slice_byte(h) for h in handles]
        return [Slice_byte.from_bytes(item) for item in data_list]
    
    # For large datasets, use multiprocessing
    if num_workers is None:
        num_workers = os.cpu_count() or 1
    
    # Split data_list evenly among processes
    chunk_size = (len(data_list) + num_workers - 1) // num_workers
    chunks = []
    for i in range(num_workers):
        start_idx = i * chunk_size
        end_idx = min(start_idx + chunk_size, len(data_list))
        if start_idx >= len(data_list):
            break
        chunks.append((i, data_list[start_idx:end_idx]))
    
    # Process in parallel
    with multiprocessing.Pool(processes=num_workers) as pool:
        chunk_results = pool.starmap(_process_chunk, chunks)
    
    # Flatten results
    results = []
    for res in chunk_results:
        results.extend(res)
    
    return results

def flatten_byte_arrays(byte_arrays: List[bytes]) -> Tuple[bytes, List[int]]:
    """
    Flatten a list of byte arrays into a single bytes object with offset metadata.
    
    Args:
        byte_arrays: List of byte arrays to flatten
        
    Returns:
        Tuple of (flattened_data, offsets) where:
          - flattened_data is a single bytes object containing all data
          - offsets is a list of (start, length) pairs for each original array
    """
    if not byte_arrays:
        return b'', []
    
    # Calculate total size
    total_size = sum(len(arr) for arr in byte_arrays)
    
    # Create offsets list (start, length pairs)
    offsets = []
    current_offset = 0
    
    for arr in byte_arrays:
        offsets.append(current_offset)  # Start offset
        offsets.append(len(arr))        # Length
        current_offset += len(arr)
    
    # Concatenate all arrays into a single bytes object
    flattened = b''.join(byte_arrays)
    
    return flattened, offsets

def _flatten_chunk(chunk_id, chunk):
    """
    Process a chunk of byte arrays in a separate process.
    
    Args:
        chunk_id: Identifier for this chunk (for debugging)
        chunk: List of byte arrays to flatten
        
    Returns:
        Tuple of (flattened_data, offsets, chunk_id)
    """
    start_time = time.perf_counter()
    
    # Calculate total size for this chunk
    total_size = sum(len(arr) for arr in chunk)
    
    # Create offsets list (start, length pairs)
    offsets = []
    current_offset = 0
    
    for arr in chunk:
        offsets.append(current_offset)  # Start offset
        offsets.append(len(arr))        # Length
        current_offset += len(arr)
    
    # Concatenate all arrays into a single bytes object
    flattened = b''.join(chunk)
    
    duration = time.perf_counter() - start_time
    print(f"Chunk {chunk_id}: Flattened {len(chunk):,} items ({total_size:,} bytes) in {duration:.3f}s", 
          file=sys.stderr)
    
    return flattened, offsets, chunk_id

def parallel_flatten_byte_arrays(byte_arrays: List[bytes], num_workers: int = None) -> Tuple[bytes, List[int]]:
    """
    Flatten a list of byte arrays in parallel using multiprocessing.
    
    Args:
        byte_arrays: List of byte arrays to flatten
        num_workers: Number of Python processes to use (defaults to CPU count)
        
    Returns:
        Tuple of (flattened_data, offsets) where:
          - flattened_data is a single bytes object containing all data
          - offsets is a list of (start, length) pairs for each original array
    """
    if not byte_arrays:
        return b'', []
    
    # For small datasets, do flattening in the current process
    if len(byte_arrays) < 10000:
        return flatten_byte_arrays(byte_arrays)
    
    # Calculate expected total size for validation
    expected_total_size = sum(len(arr) for arr in byte_arrays)
    
    # For large datasets, use multiprocessing
    if num_workers is None:
        num_workers = max(1, os.cpu_count() - 1)  # Leave one CPU for OS
    
    # Split byte_arrays evenly among processes
    chunk_size = (len(byte_arrays) + num_workers - 1) // num_workers
    chunks = []
    for i in range(num_workers):
        start_idx = i * chunk_size
        end_idx = min(start_idx + chunk_size, len(byte_arrays))
        if start_idx >= len(byte_arrays):
            break
        chunks.append((i, byte_arrays[start_idx:end_idx]))
    
    # Process in parallel
    start_time = time.perf_counter()
    with multiprocessing.Pool(processes=num_workers) as pool:
        try:
            chunk_results = pool.starmap(_flatten_chunk, chunks)
        except Exception as e:
            # Fall back to single process if parallel processing fails
            print(f"Parallel flattening failed: {e}, falling back to single process", file=sys.stderr)
            return flatten_byte_arrays(byte_arrays)
    
    # Verify all chunks were processed successfully
    if len(chunk_results) != len(chunks):
        print(f"Warning: Not all chunks processed ({len(chunk_results)} of {len(chunks)})", file=sys.stderr)
        # Fall back to single process
        return flatten_byte_arrays(byte_arrays)
    
    # Sort results by chunk_id to maintain order
    chunk_results.sort(key=lambda x: x[2])
    
    # Pre-allocate bytearray to avoid resizing penalties
    try:
        combined_size = sum(len(flattened) for flattened, _, _ in chunk_results)
        combined_data = bytearray(combined_size)
        # Add a flag to track if we're using pre-allocation
        using_prealloc = True
        current_pos = 0
    except MemoryError:
        # If pre-allocation fails, fall back to regular bytearray
        print("Warning: Pre-allocation failed, falling back to dynamic bytearray", file=sys.stderr)
        combined_data = bytearray()
        using_prealloc = False
        current_pos = 0
    
    combined_offsets = []
    offset_adjustment = 0
    
    # Verify integrity before processing each chunk
    for idx, (flattened, offsets, chunk_id) in enumerate(chunk_results):
        # Verify chunk data format
        if not isinstance(flattened, bytes) or not isinstance(offsets, list):
            print(f"Warning: Invalid data format from chunk {chunk_id}", file=sys.stderr)
            return flatten_byte_arrays(byte_arrays)
        
        # Verify offsets consistency
        if len(offsets) % 2 != 0:
            print(f"Warning: Invalid offset format from chunk {chunk_id}", file=sys.stderr)
            return flatten_byte_arrays(byte_arrays)
        
        # Verify chunk integrity - data length matches offsets
        expected_chunk_size = offsets[-2] + offsets[-1] if offsets else 0
        if len(flattened) != expected_chunk_size:
            print(f"Warning: Chunk {chunk_id} data size mismatch: {len(flattened)} vs {expected_chunk_size}", 
                  file=sys.stderr)
            return flatten_byte_arrays(byte_arrays)
            
        # Adjust offsets to account for previous chunks
        for i in range(0, len(offsets), 2):
            combined_offsets.append(offsets[i] + offset_adjustment)  # Adjusted start
            combined_offsets.append(offsets[i+1])                    # Length (unchanged)
        
        # Append flattened data - handle both pre-allocated and dynamic bytearray
        try:
            if using_prealloc:
                # Using pre-allocated array, copy data to specific position
                combined_data[current_pos:current_pos+len(flattened)] = flattened
                current_pos += len(flattened)
            else:
                # Using dynamic array
                combined_data.extend(flattened)
        except Exception as e:
            print(f"Error combining chunk {chunk_id}: {e}, falling back to single process", file=sys.stderr)
            return flatten_byte_arrays(byte_arrays)
        
        # Update offset adjustment for next chunk
        offset_adjustment += len(flattened)
    
    # Final verification: ensure combined size matches expected size
    final_result = bytes(combined_data)
    if len(final_result) != expected_total_size:
        print(f"Warning: Final data size mismatch: {len(final_result)} vs {expected_total_size}", 
              file=sys.stderr)
        return flatten_byte_arrays(byte_arrays)
    
    # Check combined offsets integrity
    if len(combined_offsets) != len(byte_arrays) * 2:
        print(f"Warning: Offset count mismatch: {len(combined_offsets)//2} vs {len(byte_arrays)}", 
              file=sys.stderr)
        return flatten_byte_arrays(byte_arrays)
    
    duration = time.perf_counter() - start_time
    print(f"Parallel flattening: Combined {len(byte_arrays):,} items ({len(final_result):,} bytes) in {duration:.3f}s", 
          file=sys.stderr)
    
    return final_result, combined_offsets

# Function to process a chunk of bytes
def _convert_slice_chunk(chunk_bytes):
    try:
        from .generated.go import Slice_byte
        return Slice_byte.from_bytes(chunk_bytes)
    except Exception as e:
        print(f"Error converting chunk: {e}", file=sys.stderr)
        # Return empty slice on error
        raise ValueError(f"Failed to convert chunk: {e}")

def prepare_flattened_data_for_go(flat_data: bytes, offsets: List[int], method="fallback"):
    """
    Convert flattened Python data to Go-compatible types.
    
    Args:
        flat_data: Flattened byte data
        offsets: List of offsets (start, length pairs)
        
    Returns:
        Tuple of (go_flat_data, go_offsets) ready for passing to Go functions
    """
    try:
        from .generated.go import Slice_byte, Slice_int
        
        # For small data, use the direct approach (avoid multiprocessing overhead)
        if len(flat_data) < 10_000_000:  # 10MB threshold
            go_flat_data = Slice_byte.from_bytes(flat_data)
            go_offsets = Slice_int(offsets)
            return go_flat_data, go_offsets
        
        if method == "fallback":
            go_flat_data = Slice_byte.from_bytes(flat_data)
            go_offsets = Slice_int(offsets)
            return go_flat_data, go_offsets
            
        

        
        # Determine optimal chunk size and worker count
        num_workers = os.cpu_count()
        # Target ~50MB chunks for optimal throughput
        target_chunk_size = 50_000_000
        
        # Calculate actual chunk size based on data size and worker count
        total_bytes = len(flat_data)
        chunk_size = max(1_000_000, min(target_chunk_size, 
                                       (total_bytes + num_workers - 1) // num_workers))
        
        # Split the data into chunks
        chunks = []
        for i in range(0, len(flat_data), chunk_size):
            chunks.append(flat_data[i:i+chunk_size])
            
        print(f"Processing {len(flat_data):,} bytes in {len(chunks)} chunks of ~{chunk_size:,} bytes each",
              file=sys.stderr)
        
        # Process chunks in parallel
        start_time = time.perf_counter()
        with multiprocessing.Pool(processes=min(num_workers, len(chunks))) as pool:
            try:
                chunk_results = pool.map(_convert_slice_chunk, chunks)
                
                # Verify all chunks were processed
                if len(chunk_results) != len(chunks):
                    print(f"Warning: Not all chunks processed. Expected {len(chunks)}, got {len(chunk_results)}", 
                          file=sys.stderr)
                    # Fall back to single-process approach
                    go_flat_data = Slice_byte.from_bytes(flat_data)
                    go_offsets = Slice_int(offsets)
                    return go_flat_data, go_offsets
                    
                # Combine the chunks into one Slice_byte
                # Start with the first chunk
                combined = chunk_results[0]
                
                # Append remaining chunks
                for chunk in chunk_results[1:]:
                    # Verify the combined object has an append method
                    if hasattr(combined, 'append'):
                        try:
                            combined.append(chunk)
                        except Exception as e:
                            print(f"Error appending chunk: {e}", file=sys.stderr)
                            # Fall back to direct conversion
                            combined = Slice_byte.from_bytes(flat_data)
                            break
                    else:
                        # If append isn't available, fall back to direct method
                        print("Warning: Slice_byte doesn't support append, using direct method", 
                              file=sys.stderr)
                        combined = Slice_byte.from_bytes(flat_data)
                        break
                
                duration = time.perf_counter() - start_time
                print(f"Parallel conversion: Processed {len(flat_data):,} bytes in {duration:.3f}s", 
                      file=sys.stderr)
                
                go_flat_data = combined
                
            except Exception as e:
                print(f"Error in parallel processing: {e}, falling back to direct method", 
                      file=sys.stderr)
                # Fall back to direct method
                go_flat_data = Slice_byte.from_bytes(flat_data)
        
        # Convert offsets to Go Slice_int (this is usually fast enough to not need parallelization)
        go_offsets = Slice_int(offsets)
        
        return go_flat_data, go_offsets
        
    except ImportError:
        print("Warning: Go types not available, returning Python types", file=sys.stderr)
        return flat_data, offsets
