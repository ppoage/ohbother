#!/usr/bin/env python3
"""
Example demonstrating efficient processing of large datasets with ohbother.

This example generates a dataset of random packets, processes them using
multiprocessing in Python and Go, and computes hashes of the data.
"""

import os
import sys
import time
import random
import multiprocessing
import array
from typing import List, Optional, Tuple
import hashlib

# Add the project root directory to Python's path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Test parameters
ITEM_COUNT = 40_000_000  # 40 million items
ITEM_SIZE = 60  # 60 bytes per item
WORKER_COUNT = max(1, multiprocessing.cpu_count() - 1)  # Leave one CPU for OS

def benchmark(func):
    """Decorator to benchmark a function"""
    def wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        duration = time.perf_counter() - start_time
        print(f"{func.__name__} took {duration:.3f} seconds")
        return result
    return wrapper

def generate_random_chunk(chunk_id: int, start_idx: int, end_idx: int, size: int) -> List[bytes]:
    """Generate a chunk of random byte arrays in a separate process - optimized version"""
    t0 = time.perf_counter()
    # Set a consistent seed per chunk
    random.seed(chunk_id * 1000 + start_idx)
    
    # Calculate chunk size
    chunk_size = end_idx - start_idx
    result = []
    
    # Generate data in batches for better performance
    batch_size = min(100_000, chunk_size)
    remaining = chunk_size
    
    while remaining > 0:
        # Process in batches
        curr_batch = min(batch_size, remaining)
        # Generate all random bytes for the batch at once
        all_bytes = os.urandom(curr_batch * size)
        
        # Slice into individual items
        for i in range(curr_batch):
            start = i * size
            end = start + size
            result.append(all_bytes[start:end])
        
        remaining -= curr_batch
        
        # Report progress for large chunks
        items_so_far = len(result)
        if items_so_far % 1_000_000 == 0 or remaining == 0:
            print(f"Chunk {chunk_id}: Generated {items_so_far:,} items so far")
    
    duration = time.perf_counter() - t0
    rate = chunk_size / duration if duration > 0 else 0
    print(f"Chunk {chunk_id}: Generated {chunk_size:,} items in {duration:.3f}s ({rate:.0f} items/s)")
    return result

@benchmark
def generate_parallel(count: int, size: int) -> List[bytes]:
    """Generate random byte arrays using multiprocessing with detailed benchmarks"""
    t0_setup = time.perf_counter()
    
    # Calculate optimal chunk size based on number of workers
    num_workers = WORKER_COUNT
    chunk_size = (count + num_workers - 1) // num_workers
    
    print(f"Generating {count:,} random byte arrays of size {size} using {num_workers} processes")
    
    # Split work into chunks
    chunks = []
    for i in range(num_workers):
        start_idx = i * chunk_size
        end_idx = min(start_idx + chunk_size, count)
        if start_idx >= count:
            break
        chunks.append((i, start_idx, end_idx, size))
    
    setup_time = time.perf_counter() - t0_setup
    print(f"Setup for parallel generation: {setup_time:.3f}s")
    
    # Process in parallel
    t0_pool = time.perf_counter()
    with multiprocessing.Pool(processes=num_workers) as pool:
        results = pool.starmap(generate_random_chunk, chunks)
    
    pool_time = time.perf_counter() - t0_pool
    print(f"Pool execution time: {pool_time:.3f}s")
    
    # Combine results
    t0_combine = time.perf_counter()
    data = []
    for i, chunk in enumerate(results):
        print(f"Combining chunk {i+1}/{len(chunks)}: {len(chunk):,} items")
        data.extend(chunk)
    
    combine_time = time.perf_counter() - t0_combine
    print(f"Result combination time: {combine_time:.3f}s")
    
    total_time = setup_time + pool_time + combine_time
    print(f"Generated {len(data):,} random byte arrays in {total_time:.3f}s")
    print(f"Generation rate: {len(data)/total_time:,.0f} items/second")
    print(f"  - Setup: {setup_time:.3f}s ({setup_time/total_time*100:.1f}%)")
    print(f"  - Pool execution: {pool_time:.3f}s ({pool_time/total_time*100:.1f}%)")
    print(f"  - Result combination: {combine_time:.3f}s ({combine_time/total_time*100:.1f}%)")
    
    return data

def process_chunk(chunk_id: int, data_chunk: List[bytes]) -> Tuple[str, str]:
    """Process a chunk of data in a separate process to find shortest/longest hash"""
    # Detailed timing within the chunk processing
    t0 = time.perf_counter()
    
    shortest_hash = None
    longest_hash = None
    processed = 0
    
    # Process the chunk of data
    for item in data_chunk:
        # Compute SHA-256 hash
        hash_value = hashlib.sha256(item).hexdigest()
        
        # Update shortest hash
        if shortest_hash is None or hash_value < shortest_hash:
            shortest_hash = hash_value
        
        # Update longest hash
        if longest_hash is None or hash_value > longest_hash:
            longest_hash = hash_value
        
        processed += 1
        if processed % 1_000_000 == 0:
            duration = time.perf_counter() - t0
            print(f"Chunk {chunk_id}: Processed {processed:,} items ({processed/len(data_chunk)*100:.1f}%) "
                  f"at {processed/duration:,.0f} items/second")
    
    duration = time.perf_counter() - t0
    print(f"Chunk {chunk_id}: Completed {processed:,} items in {duration:.3f}s "
          f"({processed/duration:,.0f} items/second)")
    
    return (shortest_hash, longest_hash)

@benchmark
def process_parallel(data: List[bytes]) -> Tuple[str, str, int]:
    """Process data using Python multiprocessing with detailed benchmarks"""
    t0_setup = time.perf_counter()
    
    # Calculate optimal chunk size
    num_workers = WORKER_COUNT
    chunk_size = (len(data) + num_workers - 1) // num_workers
    
    print(f"Processing {len(data):,} items with {num_workers} Python processes")
    
    # Split data into chunks
    chunks = []
    for i in range(num_workers):
        start_idx = i * chunk_size
        end_idx = min(start_idx + chunk_size, len(data))
        if start_idx >= len(data):
            break
        chunks.append((i, data[start_idx:end_idx]))
    
    setup_time = time.perf_counter() - t0_setup
    print(f"Setup for parallel processing: {setup_time:.3f}s")
    
    # Process in parallel
    t0_pool = time.perf_counter()
    with multiprocessing.Pool(processes=num_workers) as pool:
        results = pool.starmap(process_chunk, chunks)
    
    pool_time = time.perf_counter() - t0_pool
    print(f"Pool execution time: {pool_time:.3f}s")
    
    # Find global shortest and longest hashes
    t0_combine = time.perf_counter()
    shortest_hash = None
    longest_hash = None
    
    for chunk_shortest, chunk_longest in results:
        if shortest_hash is None or chunk_shortest < shortest_hash:
            shortest_hash = chunk_shortest
        
        if longest_hash is None or chunk_longest > longest_hash:
            longest_hash = chunk_longest
    
    combine_time = time.perf_counter() - t0_combine
    
    total_time = setup_time + pool_time + combine_time
    print(f"All processing completed in {total_time:.3f}s")
    print(f"Processing rate: {len(data)/total_time:,.0f} items/second")
    print(f"  - Setup: {setup_time:.3f}s ({setup_time/total_time*100:.1f}%)")
    print(f"  - Pool execution: {pool_time:.3f}s ({pool_time/total_time*100:.1f}%)")
    print(f"  - Result combination: {combine_time:.3f}s ({combine_time/total_time*100:.1f}%)")
    
    return (shortest_hash, longest_hash, len(data))

@benchmark
def run_benchmark():
    """Run the benchmark with detailed timing for each phase"""
    # Print memory calculations
    print(f"\n--- Large Dataset Benchmark ({ITEM_COUNT:,} items, {ITEM_SIZE} bytes each) ---")
    print(f"Using {WORKER_COUNT} worker processes")
    print(f"Expected memory usage: ~{(ITEM_COUNT * ITEM_SIZE) / (1024**3):.2f} GB")
    
    # Start timing the entire benchmark
    benchmark_start = time.perf_counter()
    
    # Step 1: Generate test data with timing
    print("\nStep 1: Generating random test data...")
    gen_start = time.perf_counter()
    data = generate_parallel(ITEM_COUNT, ITEM_SIZE)
    gen_time = time.perf_counter() - gen_start
    print(f"Data generation step complete: {gen_time:.3f}s")
    
    # Step 2: Process data with timing
    print("\nStep 2: Processing data with Python multiprocessing...")
    process_start = time.perf_counter()
    shortest_hash, longest_hash, count = process_parallel(data)
    process_time = time.perf_counter() - process_start
    print(f"Data processing step complete: {process_time:.3f}s")
    
    # Calculate and display full benchmark results
    benchmark_total = time.perf_counter() - benchmark_start
    print("\n--- Benchmark Results ---")
    print(f"Total benchmark time: {benchmark_total:.3f}s")
    print(f"Data generation: {gen_time:.3f}s ({gen_time/benchmark_total*100:.1f}%)")
    print(f"Data processing: {process_time:.3f}s ({process_time/benchmark_total*100:.1f}%)")
    
    print("\n--- Hash Results ---")
    print(f"Shortest hash: {shortest_hash}")
    print(f"Longest hash: {longest_hash}")
    print(f"Processed count: {count:,}")
    
    return {
        "total_time": benchmark_total,
        "generation_time": gen_time,
        "processing_time": process_time,
        "item_count": count,
        "shortest_hash": shortest_hash,
        "longest_hash": longest_hash
    }

if __name__ == "__main__":
    # Print system information
    print(f"Python version: {sys.version}")
    print(f"CPU count: {multiprocessing.cpu_count()}")
    print(f"Worker count: {WORKER_COUNT}")
    
    # Run the benchmark
    results = run_benchmark()
    
    # Final summary
    print("\n=== Final Performance Summary ===")
    print(f"Total throughput: {ITEM_COUNT/results['total_time']:,.0f} items/second overall")
    print(f"Generation throughput: {ITEM_COUNT/results['generation_time']:,.0f} items/second")
    print(f"Processing throughput: {ITEM_COUNT/results['processing_time']:,.0f} items/second")