This is an example for shuttling data between python and Go in a sharded manner to try and cut down 70% of the throughput bottleneck.

Python version: 3.12.3 (v3.12.3:f6650f9ad7, Apr  9 2024, 08:18:47) [Clang 13.0.0 (clang-1300.0.29.30)]
CPU count: 12
Worker count: 11

--- Large Dataset Benchmark (40,000,000 items, 60 bytes each) ---
Using 11 worker processes
Expected memory usage: ~2.24 GB

Step 1: Generating random test data...
Generating 40,000,000 random byte arrays of size 60 using 11 processes
Setup for parallel generation: 0.000s

Pool execution time: 11.570s
Result combination time: 0.122s

Generated 40,000,000 random byte arrays in 11.692s
Generation rate: 3,421,073 items/second
  - Setup: 0.000s (0.0%)
  - Pool execution: 11.570s (99.0%)
  - Result combination: 0.122s (1.0%)
generate_parallel took 11.774 seconds
Data generation step complete: 11.774s

Step 2: Processing data with Python multiprocessing...
Processing 40,000,000 items with 11 Python processes
Setup for parallel processing: 0.104s

Pool execution time: 8.777s
All processing completed in 8.881s
Processing rate: 4,504,195 items/second
  - Setup: 0.104s (1.2%)
  - Pool execution: 8.777s (98.8%)
  - Result combination: 0.000s (0.0%)
process_parallel took 8.960 seconds
Data processing step complete: 8.960s

--- Benchmark Results ---
Total benchmark time: 20.734s
Data generation: 11.774s (56.8%)
Data processing: 8.960s (43.2%)

--- Hash Results ---
Shortest hash: 0000007410e9cf2efd4ddd08be4807c02ed06e8c272769f4f91a77632029eed8
Longest hash: fffffed3419905f946ac8a3328ca3aa830c140a4311c141797b03176a291f563
Processed count: 40,000,000
run_benchmark took 20.959 seconds

=== Final Performance Summary ===
Total throughput: 1,929,171 items/second overall
Generation throughput: 3,397,360 items/second
Processing throughput: 4,464,068 items/second

Previously took 55 seconds to do an equivalent "Data Processing" step