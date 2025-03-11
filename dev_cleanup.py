#!/usr/bin/env python3
"""
Development cleanup and rebuild script for ohbother.

This script:
1. Uninstalls ohbother with pip
2. Removes old wheels from /dist
3. Builds new wheels with poetry
4. Installs the new wheel
"""

import os
import shutil
import subprocess
import glob
from pathlib import Path
import sys
import time

def run_command(cmd, description, check=True):
    """Run a command with nice output formatting."""
    print(f"\n{'='*80}\n{description}\n{'='*80}")
    result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    
    if result.stdout:
        print(f"STDOUT:\n{result.stdout}")
    if result.stderr:
        print(f"STDERR:\n{result.stderr}")
        
    if check and result.returncode != 0:
        print(f"ERROR: Command failed with exit code {result.returncode}")
        sys.exit(result.returncode)
    
    return result

def main():
    """Main function to clean up and rebuild."""
    print(f"ohbother Development Cleanup and Rebuild")
    print(f"Started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 1. Uninstall existing package
    run_command("pip uninstall -y ohbother", "Uninstalling existing ohbother package", check=False)
    
    # 2. Clean up dist directory
    dist_dir = Path("dist")
    if dist_dir.exists():
        print(f"\n{'='*80}\nCleaning up {dist_dir} directory\n{'='*80}")
        for wheel in dist_dir.glob("*.whl"):
            print(f"Removing old wheel: {wheel}")
            wheel.unlink()
        for tarball in dist_dir.glob("*.tar.gz"):
            print(f"Removing old tarball: {tarball}")
            tarball.unlink()
    else:
        dist_dir.mkdir(exist_ok=True)
        print(f"Created dist directory: {dist_dir.resolve()}")
    
    # 3. Build with poetry
    run_command("python build.py --poetry", "Building new wheel with poetry")
    
    # 4. Find and install the new wheel
    wheels = list(dist_dir.glob("*.whl"))
    if not wheels:
        print("ERROR: No wheels found in dist directory after build")
        sys.exit(1)
    
    # Sort by creation time to get the newest wheel
    newest_wheel = sorted(wheels, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    print(f"\nFound newest wheel: {newest_wheel}")
    
    # Install the wheel
    run_command(f"pip install {newest_wheel}", f"Installing {newest_wheel.name}")
    
    print(f"\n{'='*80}")
    print(f"✅ ohbother rebuilt and installed successfully!")
    print(f"Finished at: {time.strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()