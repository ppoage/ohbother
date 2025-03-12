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
        chunk_results = pool.starmap(_flatten_chunk, chunks)
    
    # Combine results
    combined_data = bytearray()
    combined_offsets = []
    
    # Sort results by chunk_id to maintain order
    chunk_results.sort(key=lambda x: x[2])
    
    # Combine flattened data and adjust offsets
    offset_adjustment = 0
    for flattened, offsets, _ in chunk_results:
        # Adjust offsets to account for previous chunks
        for i in range(0, len(offsets), 2):
            combined_offsets.append(offsets[i] + offset_adjustment)  # Adjusted start
            combined_offsets.append(offsets[i+1])                    # Length (unchanged)
        
        # Append flattened data
        combined_data.extend(flattened)
        
        # Update offset adjustment for next chunk
        offset_adjustment += len(flattened)
    
    duration = time.perf_counter() - start_time
    total_size = len(combined_data)
    print(f"Parallel flattening: Combined {len(byte_arrays):,} items ({total_size:,} bytes) in {duration:.3f}s", 
          file=sys.stderr)
    
    return bytes(combined_data), combined_offsets

def prepare_flattened_data_for_go(flat_data: bytes, offsets: List[int]):
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
        
        # Convert flat_data to Go Slice_byte
        go_flat_data = Slice_byte.from_bytes(flat_data)
        
        # Convert offsets to Go Slice_int
        go_offsets = Slice_int(offsets)
        
        return go_flat_data, go_offsets
    except ImportError:
        print("Warning: Go types not available, returning Python types", file=sys.stderr)
        return flat_data, offsets
