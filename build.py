# build script for ohbother Python bindings

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
    
    # Create temporary output directory
    temp_dir = Path("ohbother/core/_generated")
    temp_dir.mkdir(parents=True, exist_ok=True)
    print(f"Temporary output directory: {temp_dir.resolve()}")
    
    # Create final destination directory
    final_dir = Path("ohbother/generated")
    final_dir.mkdir(parents=True, exist_ok=True)
    print(f"Final output directory: {final_dir.resolve()}")
    
    # Use Python interpreter path
    python_path = os.environ.get("PYTHON_VM_PATH", sys.executable)
    working_dir = Path("ohbother/core").resolve()
    print(f"Working directory: {working_dir}")
    print(f"Using Python interpreter: {python_path}")
    
    # Run gopy build with verbose flag
    cmd = [
        "gopy",
        "build",
        "-output=" + str(temp_dir.resolve()),
        "-no-make=true",
        "-vm=" + python_path,
        ".",
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=working_dir,
            env=env,
            check=True,
            capture_output=True,
            text=True
        )
        print(result.stdout)
        
        # Move generated files to final destination
        print(f"Moving generated files from {temp_dir} to {final_dir}")
        if temp_dir.exists():
            # Remove existing files in destination if they exist
            if final_dir.exists():
                for item in final_dir.glob('*'):
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
            
            # Move each item from source to destination
            for item in temp_dir.glob('*'):
                dest_path = final_dir / item.name
                if item.is_file():
                    shutil.copy2(item, dest_path)
                else:
                    shutil.copytree(item, dest_path, dirs_exist_ok=True)
            
            # Clean up temporary directory
            shutil.rmtree(temp_dir)
        
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit code {e.returncode}")
        print(f"STDOUT: {e.stdout}")
        print(f"STDERR: {e.stderr}")
        raise
    
    print("Standard build completed successfully")


def build_dev(env):
    """Run development build with additional debug info"""
    print("Running development build...")
    
    # Create temporary output directory
    temp_dir = Path("ohbother/core/_generated")
    temp_dir.mkdir(parents=True, exist_ok=True)
    print(f"Temporary output directory: {temp_dir.resolve()}")
    
    # Create final destination directory
    final_dir = Path("ohbother/generated")
    final_dir.mkdir(parents=True, exist_ok=True)
    print(f"Final output directory: {final_dir.resolve()}")
    
    # Use Python interpreter path
    python_path = sys.executable + "3.12"
    working_dir = Path("ohbother/core").resolve()
    print(f"Working directory: {working_dir}")
    print(f"Using Python interpreter: {python_path}")
    
    # Run gopy build with verbose flag
    cmd = [
        "gopy",
        "build",
        "-build-tags=" + "GOEXPERIMENT=cgocheck2",
        "-output=" + str(temp_dir.resolve()),
        "-no-make=true",
        "-vm=" + python_path,
        ".",
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=working_dir,
            env=env,
            check=True,
            capture_output=True,
            text=True
        )
        print(result.stdout)
        
        # Move generated files to final destination
        print(f"Moving generated files from {temp_dir} to {final_dir}")
        if temp_dir.exists():
            # Remove existing files in destination if they exist
            if final_dir.exists():
                for item in final_dir.glob('*'):
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
            
            # Move each item from source to destination
            for item in temp_dir.glob('*'):
                dest_path = final_dir / item.name
                if item.is_file():
                    shutil.copy2(item, dest_path)
                else:
                    shutil.copytree(item, dest_path, dirs_exist_ok=True)
            
            # Clean up temporary directory
            shutil.rmtree(temp_dir)
        
    except subprocess.CalledProcessError as e:
        print(f"Command failed with exit code {e.returncode}")
        print(f"STDOUT: {e.stdout}")
        print(f"STDERR: {e.stderr}")
        raise
    
    print("Development build completed successfully")


def make_wheel_dev(python_version='3.12', output_dir='wheelhouse'):
    """
    Build wheels locally using cibuildwheel via pipx for development testing.
    
    This function replicates what the GitHub Actions workflow does but locally.
    
    Args:
        python_version (str): Python version to build for ('3.10', '3.11', '3.12')
        output_dir (str): Directory to output wheels to
    """
    import os
    import platform
    import subprocess
    import tempfile
    import shutil
    from pathlib import Path
    
    print(f"Building wheels for Python {python_version}")
    
    
    # Determine Python version tag
    py_tag = f"cp{python_version.replace('.', '')}"
    
    # Set up environment variables
    env = os.environ.copy()
    
    # Platform specific settings
    system = platform.system()
    current_dir = os.getcwd()
    
    if system == "Windows":
        # Windows needs PATH set to include the generated directory
        env["PATH"] = f"{current_dir}\\ohbother\\generated;{env.get('PATH', '')}"
    elif system == "Darwin":  # macOS
        env["DYLD_LIBRARY_PATH"] = f"{env.get('DYLD_LIBRARY_PATH', '')}:{current_dir}/ohbother/generated"
        env["MACOSX_DEPLOYMENT_TARGET"] = "15.0"
    else:  # Linux
        env["LD_LIBRARY_PATH"] = f"{env.get('LD_LIBRARY_PATH', '')}:{current_dir}/ohbother/generated"
    
    # Common environment variables
    env["CIBW_BUILD_FRONTEND"] = "build; args:" # default: "pip"
    env["CIBW_BUILD"] = f"{py_tag}*"
    env["CIBW_SKIP"] = "*-musllinux_* *-manylinux_i686 *-win32"
    env["CIBW_TEST_SKIP"] = "*"
    env["CIBW_BEFORE_BUILD"] = "pip install setuptools wheel"
    env["CIBW_BUILD_VERBOSITY"] = "1"
    env["PIP_NO_BUILD_ISOLATION"] = "false"
    
    if system == "Darwin":
        env["CIBW_ARCHS_MACOS"] = "arm64"
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Run cibuildwheel using pipx
    print(f"Running cibuildwheel via pipx...")
    cmd = ["pipx", "run", "cibuildwheel", "--output-dir", output_dir]
    
    try:
        result = subprocess.run(cmd, env=env, check=True)
        print(f"Wheels built successfully and saved to {output_dir}/")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Error building wheels: {e}")
        return e.returncode


def make_poetry_wheel(output_dir='dist'):
    """
    Build wheels using Poetry.
    
    Args:
        output_dir (str): Directory to output wheels to (defaults to 'dist')
    """
    import os
    import subprocess
    import platform
    import shutil
    from pathlib import Path
    
    print("Building wheels using Poetry...")
    
    # Check if Poetry is installed, install if needed
    try:
        subprocess.run(["poetry", "--version"], check=True, capture_output=True)
        print("Poetry already installed")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Installing Poetry...")
        subprocess.run(["pipx", "install", "poetry"], check=True)
    
    # Make sure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Set environment variables for platform-specific settings
    env = os.environ.copy()
    system = platform.system()
    current_dir = os.getcwd()
    
    if system == "Darwin":  # macOS
        env["DYLD_LIBRARY_PATH"] = f"{env.get('DYLD_LIBRARY_PATH', '')}:{current_dir}/ohbother/generated"
        env["MACOSX_DEPLOYMENT_TARGET"] = "15.0"
    elif system == "Windows":
        env["PATH"] = f"{current_dir}\\ohbother\\generated;{env.get('PATH', '')}"
    else:  # Linux
        env["LD_LIBRARY_PATH"] = f"{env.get('LD_LIBRARY_PATH', '')}:{current_dir}/ohbother/generated"

    # Build the wheel using Poetry
    print("Building wheel with Poetry...")
    try:
        subprocess.run(["poetry", "build", "--format", "wheel"], env=env, check=True)
        
        # Copy wheels from dist/ to the specified output directory if different
        if output_dir != "dist" and os.path.exists("dist"):
            for wheel_file in Path("dist").glob("*.whl"):
                shutil.copy2(wheel_file, output_dir)
            print(f"Copied wheels to {output_dir}/")
        
        print(f"Wheels built successfully and saved to {output_dir}/")
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Error building wheels with Poetry: {e}")
        return e.returncode


def main():
    parser = argparse.ArgumentParser(description="Build ohbother Python bindings")
    parser.add_argument(
        "--dev", 
        action="store_true", 
        help="Run in development mode with more detailed output"
    )
    parser.add_argument(
        "--wheel", 
        action="store_true", 
        help="Build wheels for distribution"
    )
    parser.add_argument(
        "--poetry", 
        action="store_true", 
        help="Build wheel with poetry"
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
    elif args.wheel:
        make_wheel_dev()
    elif args.poetry:
        make_poetry_wheel()
    else:
        build_standard(env)
    
    print("\nBuild process complete!")


if __name__ == "__main__":
    main()
