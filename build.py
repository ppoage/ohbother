import os
import sys
import subprocess
import shutil
import tempfile
from setuptools import setup, find_packages, Command
from setuptools.command.build import build
from wheel.bdist_wheel import bdist_wheel

class BuildGoBindings(Command):
    description = "Build Go bindings using gopy."
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        project_root = os.getcwd()
        
        # Ensure ohbother package directory exists
        if not os.path.exists("ohbother"):
            os.makedirs("ohbother")
        
        # Create __init__.py if it doesn't exist
        init_path = os.path.join("ohbother", "__init__.py")
        if not os.path.exists(init_path):
            with open(init_path, "w") as f:
                f.write("# Auto-generated __init__.py for ohbother package\n")
                
        # Set up Go environment with platform-specific settings
        env = os.environ.copy()
        env["CGO_ENABLED"] = "1"
        env["GO111MODULE"] = "on"  # Force module mode
        
        # Detect platform and set appropriate architecture flags
        if sys.platform.startswith('darwin'):
            # macOS
            if os.environ.get('GITHUB_ACTIONS') == 'true':
                # In GitHub Actions, use x86_64 for macOS
                env["ARCHFLAGS"] = "-arch x86_64"
                env["GOARCH"] = "amd64"
            else:
                # Local development could use arm64 for M1/M2 Macs
                env["ARCHFLAGS"] = "-arch arm64"
                env["GOARCH"] = "arm64"
            env["GOOS"] = "darwin"
            env["CC"] = "clang"
        elif sys.platform.startswith('win'):
            # Windows
            env["GOARCH"] = "amd64"
            env["GOOS"] = "windows"
        else:
            # Linux and others
            env["GOARCH"] = "amd64"
            env["GOOS"] = "linux"
            env["CC"] = "gcc"
        
        # Python interpreter path
        python_path = sys.executable
        print(f"Using Python interpreter: {python_path}")
        print(f"Platform: {sys.platform}, GOARCH: {env['GOARCH']}, GOOS: {env['GOOS']}")
        
        # Create a temporary directory for the build
        with tempfile.TemporaryDirectory() as temp_dir:
            print(f"Created temporary build directory: {temp_dir}")
            
            # Copy all Go files and go.mod from src to temp directory
            src_dir = os.path.join(project_root, "src")
            for filename in os.listdir(src_dir):
                if filename.endswith(".go") or filename == "go.mod" or filename == "go.sum":
                    src_file = os.path.join(src_dir, filename)
                    dst_file = os.path.join(temp_dir, filename)
                    shutil.copy2(src_file, dst_file)
                    print(f"Copied {src_file} to {dst_file}")
            
            # Check if go.mod exists and has correct module name
            go_mod_path = os.path.join(temp_dir, "go.mod")
            if os.path.exists(go_mod_path):
                with open(go_mod_path, "r") as f:
                    content = f.read()
                    if not content.startswith("module ohbother"):
                        # Update module name if needed
                        with open(go_mod_path, "w") as fw:
                            fw.write(content.replace("module py_gopacket", "module ohbother", 1))
                        print("Updated go.mod to use module name 'ohbother'")
            
            # Prepare environment PATH so goimports is found
            gopath = subprocess.check_output(["go", "env", "GOPATH"], env=env).decode().strip()
            env["PATH"] = env["PATH"] + ":" + os.path.join(gopath, "bin")

            # Change to the temporary directory
            os.chdir(temp_dir)
            
            # Run gopy in the temporary directory
            cmd = [
                "gopy", 
                "pkg",
                "-name", "ohbother",
                "-output", os.path.join(project_root, "temp_out"),
                "-vm", python_path,
                "."  # Use current directory as source
            ]
            print(f"Running gopy command from {os.getcwd()}: {' '.join(cmd)}")
            ret = subprocess.call(cmd, env=env, cwd=temp_dir)
        
        # Change back to project root (should happen automatically after the temp directory is deleted)
        os.chdir(project_root)
        
        if ret != 0:
            raise SystemExit("gopy pkg failed")
            
        # Copy generated files to ohbother directory
        generated_dir = os.path.join("temp_out", "ohbother")
        if os.path.exists(generated_dir):
            for item in os.listdir(generated_dir):
                src_file = os.path.join(generated_dir, item)
                dst_file = os.path.join("ohbother", item)
                if os.path.isfile(src_file):
                    shutil.copy2(src_file, dst_file)
                    print(f"Copied {src_file} to {dst_file}")
                    
            # Also copy go directory if it exists
            go_dir = os.path.join("temp_out", "go")
            if os.path.exists(go_dir):
                ohbother_go_dir = os.path.join("ohbother", "go")
                if not os.path.exists(ohbother_go_dir):
                    os.makedirs(ohbother_go_dir)
                for item in os.listdir(go_dir):
                    src_file = os.path.join(go_dir, item)
                    dst_file = os.path.join(ohbother_go_dir, item)
                    if os.path.isfile(src_file):
                        shutil.copy2(src_file, dst_file)
                        print(f"Copied {src_file} to {dst_file}")
        else:
            print(f"WARNING: Generated directory not found: {generated_dir}")
            print(f"Contents of temp_out: {os.listdir('temp_out') if os.path.exists('temp_out') else 'directory not found'}")
        
        # Clean up temporary directories
        if os.path.exists("temp_out"):
            shutil.rmtree("temp_out")

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
    long_description=open("README.md", "r", encoding="utf-8").read() if os.path.exists("README.md") else "",
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