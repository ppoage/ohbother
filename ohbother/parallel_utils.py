"""
High-performance parallel utilities for converting between Python and Go data types.

This module provides optimized functions for converting large numbers of Python
byte arrays to Go slices in parallel using both multiprocessing and Go's
native concurrency.
"""

import multiprocessing
import os
import sys
import time
from typing import List, Union, Iterable, Any
from functools import partial

# Import required Go types - use try/except only for error cases
_has_slice_byte = False
_has_optimized = False

try:
    # Fast path - just try the main import locations
    try:
        from .generated.go import Slice_byte
        from .generated.ohbother import BatchConvertPythonBytesToSlices
        _has_slice_byte = True
        _has_optimized = True
    except ImportError:
        # Try alternative import paths
        from .generated.ohbother import Slice_byte
        from .generated.ohbother import BatchConvertPythonBytesToSlices
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
    
    # First, check if the optimized path is available
    if _has_optimized:
        try:
            # Use optimized Go implementation
            handles = BatchConvertPythonBytesToSlices(chunk, 8)
            
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
            print(f"Chunk {chunk_id}: Processed {len(chunk):,} items in {duration:.3f}s", file=sys.stderr)
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
        if _has_optimized:
            handles = BatchConvertPythonBytesToSlices(data_list, num_workers or os.cpu_count())
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