"""
Data processing module for ohbother.

Provides functions for efficient processing of large datasets across
the Python-Go boundary.
"""

import os
import sys
import time
import multiprocessing
from typing import List, Dict, Any, Optional, Union, Tuple, Callable

# Use the already-exposed functions from ohbother
try:
    from ohbother.generated.go import Slice_byte
    from ohbother.generated import PayloadNative
    _has_optimized = True
except ImportError:
    _has_optimized = False
    print("Warning: Optimized Go functions not available", file=sys.stderr, flush=True)

def process_large_dataset(data: List[bytes], num_workers: Optional[int] = None) -> Tuple[str, str, int]:
    """
    Process a large dataset using Python multiprocessing.
    
    Since the direct Go implementation isn't accessible, this uses Python's
    multiprocessing to distribute the workload.
    
    Args:
        data: List of byte arrays to process
        num_workers: Number of processes to use
        
    Returns:
        (shortest_hash, longest_hash, count)
    """
    import hashlib
    
    if not data:
        return ("", "", 0)
    
    # Use all available CPUs by default
    if num_workers is None:
        num_workers = max(1, os.cpu_count() - 1)  # Leave one CPU for OS
    
    # Process function that runs in each worker
    def process_chunk(chunk_id, data_chunk):
        shortest_hash = None
        longest_hash = None
        
        for item in data_chunk:
            # Compute SHA-256 hash
            hash_value = hashlib.sha256(item).hexdigest()
            
            # Update shortest hash
            if shortest_hash is None or hash_value < shortest_hash:
                shortest_hash = hash_value
            
            # Update longest hash
            if longest_hash is None or hash_value > longest_hash:
                longest_hash = hash_value
        
        return (shortest_hash, longest_hash)
    
    # Split data into chunks
    chunk_size = (len(data) + num_workers - 1) // num_workers
    chunks = []
    
    for i in range(num_workers):
        start_idx = i * chunk_size
        end_idx = min(start_idx + chunk_size, len(data))
        if start_idx >= len(data):
            break
        chunks.append((i, data[start_idx:end_idx]))
    
    # Process in parallel
    with multiprocessing.Pool(processes=num_workers) as pool:
        results = pool.starmap(process_chunk, chunks)
    
    # Find global shortest and longest
    shortest_hash = None
    longest_hash = None
    
    for chunk_shortest, chunk_longest in results:
        if shortest_hash is None or chunk_shortest < shortest_hash:
            shortest_hash = chunk_shortest
        
        if longest_hash is None or chunk_longest > longest_hash:
            longest_hash = chunk_longest
    
    return (shortest_hash, longest_hash, len(data))

def generate_random_data(count: int, size: int, seed: Optional[int] = None) -> List[bytes]:
    """
    Generate random byte arrays in parallel using multiprocessing.
    
    Args:
        count: Number of items to generate
        size: Size of each item in bytes
        seed: Random seed for reproducibility
        
    Returns:
        List of random byte arrays
    """
    import random
    
    # Worker function for generating a chunk of data
    def generate_chunk(chunk_id, count, item_size, chunk_seed):
        # Set seed for reproducibility
        random.seed(chunk_seed + chunk_id if chunk_seed is not None else None)
        
        # Generate the data
        return [bytes(random.randint(0, 255) for _ in range(item_size)) 
                for _ in range(count)]
    
    # Determine optimal chunk configuration
    num_workers = os.cpu_count() or 1
    chunk_size = (count + num_workers - 1) // num_workers
    
    # Create tasks for each worker
    chunks = []
    for i in range(num_workers):
        worker_count = min(chunk_size, count - i * chunk_size)
        if worker_count <= 0:
            break
        chunks.append((i, worker_count, size, seed))
    
    # Generate data in parallel
    with multiprocessing.Pool(processes=num_workers) as pool:
        results = pool.starmap(generate_chunk, chunks)
    
    # Combine results
    data = []
    for chunk in results:
        data.extend(chunk)
    
    return data

def multiprocess_data_conversion(data: List[bytes], num_workers: Optional[int] = None) -> List:
    """
    Convert Python byte objects to Go objects using multiprocessing.
    
    Since the direct optimized BatchConvertPythonBytes function isn't accessible,
    this uses Python's multiprocessing to distribute the workload.
    
    Args:
        data: List of byte arrays to convert
        num_workers: Number of processes to use
        
    Returns:
        List of converted objects (Slice_byte if _has_optimized, otherwise bytes)
    """
    if not data:
        return []
    
    # Use all available CPUs by default
    if num_workers is None:
        num_workers = max(1, os.cpu_count() - 1)  # Leave one CPU for OS
    
    # Convert function that runs in each worker
    def convert_chunk(data_chunk):
        if _has_optimized:
            # Use the available Go function
            return [Slice_byte.from_bytes(item) for item in data_chunk]
        else:
            # Just return the bytes
            return data_chunk
    
    # Split data into chunks
    chunk_size = (len(data) + num_workers - 1) // num_workers
    chunks = []
    
    for i in range(num_workers):
        start_idx = i * chunk_size
        end_idx = min(start_idx + chunk_size, len(data))
        if start_idx >= len(data):
            break
        chunks.append(data[start_idx:end_idx])
    
    # Process in parallel
    with multiprocessing.Pool(processes=num_workers) as pool:
        results = pool.map(convert_chunk, chunks)
    
    # Combine results
    converted = []
    for chunk in results:
        converted.extend(chunk)
    
    return converted