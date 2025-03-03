import os
import sys
import subprocess
import shutil
import tempfile
from setuptools import setup, find_packages, Command
from setuptools.command.build import build
from wheel.bdist_wheel import bdist_wheel

# Define project_root as one directory above src/
project_root = os.path.dirname(os.getcwd())

class BuildGoBindings(Command):
    description = "Build Go bindings using gopy."
    user_options = []  # No options for this command

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        print(f"Current working directory: {os.getcwd()}")
        
        # Create ohbother directory in project root
        ohbother_dir = os.path.join(project_root, "ohbother")
        if not os.path.exists(ohbother_dir):
            os.makedirs(ohbother_dir)
            print(f"Created directory: {ohbother_dir}")
        
        # Initialize module
        init_path = os.path.join(ohbother_dir, "__init__.py")
        if not os.path.exists(init_path):
            with open(init_path, "w") as f:
                f.write("# Auto-generated __init__.py\n")
                print(f"Created: {init_path}")
        
        # Copy current environment and set platform-specific flags
        env = os.environ.copy()
        env["CGO_ENABLED"] = "1"
        env["GO111MODULE"] = "on"
        
        # Platform detection with special handling for Windows
        if sys.platform.startswith('darwin'):
            if os.environ.get('GITHUB_ACTIONS') == 'true':
                env["ARCHFLAGS"] = "-arch x86_64"
                env["GOARCH"] = "amd64"
            else:
                env["ARCHFLAGS"] = "-arch arm64"
                env["GOARCH"] = "arm64"
            env["GOOS"] = "darwin"
            env["CC"] = "clang"
        elif sys.platform.startswith('win'):
            env["GOARCH"] = "amd64"
            env["GOOS"] = "windows"
            
            # Get Python version components for library naming
            py_version = sys.version_info
            py_lib_name = f"python{py_version.major}{py_version.minor}"
            
            # Extract Python library path from the interpreter path
            python_base = os.path.dirname(sys.executable)
            python_libs = os.path.join(python_base, 'libs')
            
            # Set Windows-specific environment variables for gopy
            if os.path.exists(python_libs):
                print(f"Found Python libs directory: {python_libs}")
                env["GOPY_LIBDIR"] = python_libs
                env["GOPY_PYLIB"] = py_lib_name
                print(f"Set GOPY_LIBDIR={python_libs}, GOPY_PYLIB={py_lib_name}")
            else:
                print(f"WARNING: Python libs directory not found at {python_libs}")
        else:  # Linux and others
            env["GOARCH"] = "amd64"
            env["GOOS"] = "linux"
            env["CC"] = "gcc"
        
        # Update the python_path handling for Windows:

        # Use environment var if set (for CI), otherwise use sys.executable (for local dev)
        python_path = os.environ.get('PYTHON_VM_PATH', sys.executable)

        # For Windows, explicitly use python3.exe instead of python.exe
        if sys.platform.startswith('win'):
            # Get directory containing the python executable
            python_dir = os.path.dirname(python_path)
            
            # Create path to python3.exe
            python3_path = os.path.join(python_dir, 'python3.exe')
            
            # Check if python3.exe exists (it should because of our symlink step)
            if os.path.exists(python3_path):
                print(f"Found python3.exe: {python3_path}")
                python_path = python3_path
            else:
                print(f"WARNING: python3.exe not found in {python_dir}, using {python_path}")

        print(f"Using Python interpreter: {python_path} (from {'environment' if 'PYTHON_VM_PATH' in os.environ else 'sys.executable'})")
        print(f"Platform: {sys.platform}, GOARCH: {env.get('GOARCH')}, GOOS: {env.get('GOOS')}")
        
        # Add this debug code before running the gopy command:

        # Print important environment variables for debugging
        print(f"PYTHON_VM_PATH = {os.environ.get('PYTHON_VM_PATH', 'not set')}")
        print(f"GOPY_LIBDIR = {os.environ.get('GOPY_LIBDIR', 'not set')}")
        print(f"GOPY_PYLIB = {os.environ.get('GOPY_PYLIB', 'not set')}")

        # Use full paths for Windows to avoid directory confusion
        ohbother_output_dir = os.path.join(project_root, "ohbother")

        # Run gopy command with platform-specific paths
        cmd = [
            "gopy",
            "pkg",
            "-name", "ohbother"
        ]

        # Use absolute paths on Windows
        if sys.platform.startswith('win'):
            # Convert Windows path to use forward slashes for commandline tools
            
            cmd.extend(["-output", "ohbother"])
            # Also normalize Python path
            cmd.extend(["-vm", python_path.replace('\\', '/')])
            cmd.append("ohbother")
        else:
            # Unix systems can use relative paths
            cmd.extend(["-output", "ohbother"])
            cmd.extend(["-vm", python_path])
            cmd.append("ohbother")
        
        print(f"Running gopy command: {' '.join(cmd)}")
        ret = subprocess.call(cmd, env=env)
        if ret != 0:
            raise SystemExit("gopy pkg failed")

class CustomBuild(build):
    def run(self):
        self.run_command("build_go")
        super().run()

class CustomBdistWheel(bdist_wheel):
    def run(self):
        self.run_command("build_go")
        super().run()

# Read README from project root, not src directory
readme_path = os.path.join(project_root, "README.md")
long_description = ""
if os.path.exists(readme_path):
    with open(readme_path, "r", encoding="utf-8") as fh:
        long_description = fh.read()

setup(
    name="ohbother",
    version="0.1",
    packages=find_packages(),
    package_data={
        "ohbother": ["*.so", "*.dll", "*.dylib", "*.pyd", "go/*.py", "go/*.so"],
    },
    description="High-performance UDP packet transmitter/receiver built in Go with Python bindings",
    long_description=long_description,
    long_description_content_type="text/markdown",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Go",
        "Operating System :: OS Independent",
    ],
    cmdclass={
        "build_go": BuildGoBindings,
        "build": CustomBuild,
        "bdist_wheel": CustomBdistWheel,
    },
    python_requires='>=3.6',
)