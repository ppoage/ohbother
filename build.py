# build script for whatsapp extensions

import os
import sys
import subprocess
import shutil
import argparse
from pathlib import Path


def setup_environment():
    """Configure environment variables for the build"""
    env = os.environ.copy()
    
    # Basic Go settings
    env["CGO_ENABLED"] = "1"
    env["GO111MODULE"] = "on"
    
    # Set PATH to include go binaries
    env["PATH"] = os.path.expanduser("~/go/bin") + ":" + env.get("PATH", "")
    
    # Platform-specific settings
    if sys.platform.startswith("darwin"):
        arch = subprocess.check_output(["uname", "-m"]).decode("utf-8").strip()
        if arch == "arm64":
            print("Building for Apple Silicon (arm64)")
            env["ARCHFLAGS"] = "-arch arm64"
            env["GOARCH"] = "arm64"
        else:
            print("Building for Intel Mac (x86_64)")
            env["ARCHFLAGS"] = "-arch x86_64"
            env["GOARCH"] = "amd64"
        env["GOOS"] = "darwin"
        env["CC"] = "clang"
    elif sys.platform.startswith("win"):
        env["GOARCH"] = "amd64"
        env["GOOS"] = "windows"
        
        # Python library settings for Windows
        py_version = sys.version_info
        py_lib_name = f"python{py_version.major}{py_version.minor}"
        python_base = os.path.dirname(sys.executable)
        python_libs = os.path.join(python_base, "libs")
        
        if os.path.exists(python_libs):
            env["GOPY_LIBDIR"] = python_libs
            env["GOPY_PYLIB"] = py_lib_name
    else:  # Linux and others
        env["GOARCH"] = "amd64"
        env["GOOS"] = "linux"
        env["CC"] = "gcc"
    
    return env


def install_go_deps():
    """Install required Go tools"""
    print("Installing Go dependencies...")
    subprocess.run(["go", "install", "github.com/go-python/gopy@master"], check=True)
    subprocess.run(["go", "install", "golang.org/x/tools/cmd/goimports@latest"], check=True)


def build_standard(env):
    """Run standard production build"""
    print("Running standard build...")
    
    # Create output directory if it doesn't exist
    output_dir = Path("ohbother/generated")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Run gopy build
    subprocess.run(
        [
            "gopy",
            "build",
            "-output=generated",
            "-no-make=true",
            ".",
        ],
        cwd=Path("ohbother"),
        env=env,
        check=True,
    )
    
    print("Standard build completed successfully")


def build_dev(env):
    """Run development build with additional debug info"""
    print("Running development build...")
    
    # Create output directory if it doesn't exist
    output_dir = Path("ohbother/generated")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Use Python interpreter path
    python_path = sys.executable
    print(f"Using Python interpreter: {python_path}")
    
    # Run gopy build with verbose flag
    subprocess.run(
        [
            "gopy",
            "build",
            "-output=generated",
            "-no-make=true",
            "-vm=" + python_path,
            "-v",  # Verbose output for development
            ".",
        ],
        cwd=Path("ohbother"),
        env=env,
        check=True,
    )
    
    print("Development build completed successfully")


def main():
    parser = argparse.ArgumentParser(description="Build ohbother Python bindings")
    parser.add_argument(
        "--dev", 
        action="store_true", 
        help="Run in development mode with more detailed output"
    )
    args = parser.parse_args()
    
    # Install Go dependencies
    install_go_deps()
    
    # Setup environment
    env = setup_environment()
    
    # Print build information
    print(f"Platform: {sys.platform}, GOARCH: {env.get('GOARCH')}, GOOS: {env.get('GOOS')}")
    
    # Run appropriate build
    if args.dev:
        build_dev(env)
    else:
        build_standard(env)
    
    print("\nBuild process complete!")


if __name__ == "__main__":
    main()
