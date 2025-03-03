import os
import sys
import subprocess
import shutil
import tempfile
from setuptools import setup, find_packages, Command
from setuptools.command.build import build
from wheel.bdist_wheel import bdist_wheel

# Define project_root in the global scope - this is correct
project_root = os.path.dirname(os.getcwd())  # Go up one directory from src/
print(f"Project root: {project_root}")

class BuildGoBindings(Command):
    description = "Build Go bindings using gopy"
    user_options = []

    def initialize_options(self):
        pass
        
    def finalize_options(self):
        pass

    def run(self):
        print(f"Current working directory: {os.getcwd()}")
        print(f"Building Go bindings from: {__file__}")
        
        # Use consistent path calculations with project_root variable
        ohbother_dir = os.path.join(project_root, "ohbother")
        temp_out_dir = os.path.join(project_root, "temp_out")
        
        print(f"Output directory: {ohbother_dir}")
        print(f"Temp output directory: {temp_out_dir}")
        
        if not os.path.exists(ohbother_dir):
            os.makedirs(ohbother_dir)
            print(f"Created directory: {ohbother_dir}")
        
        # Initialize module
        init_path = os.path.join(ohbother_dir, "__init__.py")
        if not os.path.exists(init_path):
            with open(init_path, "w") as f:
                f.write("# Auto-generated __init__.py\n")
                print(f"Created: {init_path}")
                
        # Run gopy command with absolute paths
        python_path = sys.executable
        cmd = [
            "gopy", "pkg",
            "-name", "ohbother",
            "-output", temp_out_dir,
            "-vm", python_path,
            "."
        ]
        print(f"Running: {' '.join(cmd)}")
        # Print environment info for debugging
        print(f"PATH: {os.environ.get('PATH')}")
        print(f"Go files in current directory: {[f for f in os.listdir('.') if f.endswith('.go')]}")
        
        ret = subprocess.call(cmd)
        print(f"gopy command returned: {ret}")
        
        # Copy output files if generated
        generated_dir = os.path.join(temp_out_dir, "ohbother")
        if os.path.exists(generated_dir):
            print(f"Generated files found in: {generated_dir}")
            for item in os.listdir(generated_dir):
                src_file = os.path.join(generated_dir, item)
                dst_file = os.path.join(ohbother_dir, item)
                if os.path.isfile(src_file):
                    shutil.copy2(src_file, dst_file)
                    print(f"Copied: {src_file} to {dst_file}")
                    
        if ret != 0:
            raise SystemExit("gopy failed")

class CustomBuild(build):
    def run(self):
        self.run_command("build_go")
        super().run()

class CustomBdistWheel(bdist_wheel):
    def run(self):
        self.run_command("build_go")
        super().run()

# Rest of your setup function
setup(
    name="ohbother",
    version="0.1",
    packages=find_packages(),
    package_data={
        "ohbother": ["*.so", "*.dll", "*.dylib", "*.pyd", "go/*.py", "go/*.so"],
    },
    description="High-performance UDP packet transmitter/receiver built in Go with Python bindings",
    long_description=open(os.path.join(project_root, "README.md"), "r", encoding="utf-8").read() if os.path.exists(os.path.join(project_root, "README.md")) else "",
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