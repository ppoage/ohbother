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
        src_dir = os.path.join(project_root, "src")
        if not os.path.isdir(src_dir):
            raise SystemExit("src folder not found.")

        # Change to src folder so go.mod and go files are found
        os.chdir(src_dir)
        print(f"Changed working directory to {src_dir}")

        # Ensure ohbother package directory exists at the project root
        ohbother_dir = os.path.join(project_root, "ohbother")
        if not os.path.exists(ohbother_dir):
            os.makedirs(ohbother_dir)
        init_path = os.path.join(ohbother_dir, "__init__.py")
        if not os.path.exists(init_path):
            with open(init_path, "w") as f:
                f.write("# Auto-generated __init__.py for ohbother package\n")

        # Set up Go environment with platform-specific settings
        env = os.environ.copy()
        env["CGO_ENABLED"] = "1"
        env["GO111MODULE"] = "on"
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
        else:
            env["GOARCH"] = "amd64"
            env["GOOS"] = "linux"
            env["CC"] = "gcc"

        python_path = sys.executable
        print(f"Using Python interpreter: {python_path}")
        print(f"Platform: {sys.platform}, GOARCH: {env['GOARCH']}, GOOS: {env['GOOS']}")

        # Create a temporary directory for the build and copy files from src (now current dir)
        with tempfile.TemporaryDirectory() as temp_dir:
            print(f"Created temporary build directory: {temp_dir}")
            for filename in os.listdir("."):
                if filename.endswith(".go") or filename in ("go.mod", "go.sum"):
                    shutil.copy2(filename, os.path.join(temp_dir, filename))
                    print(f"Copied {filename} to temp directory")
            
            # Optionally update go.mod if needed
            go_mod_path = os.path.join(temp_dir, "go.mod")
            if os.path.exists(go_mod_path):
                with open(go_mod_path, "r") as f:
                    content = f.read()
                if not content.startswith("module ohbother"):
                    with open(go_mod_path, "w") as fw:
                        fw.write(content.replace("module py_gopacket", "module ohbother", 1))
                    print("Updated go.mod to use module name 'ohbother'")

            # Add GOPATH/bin to PATH so goimports is found
            gopath = subprocess.check_output(["go", "env", "GOPATH"], env=env).decode().strip()
            env["PATH"] = env["PATH"] + ":" + os.path.join(gopath, "bin")

            # Change to the temporary directory and run gopy
            os.chdir(temp_dir)
            cmd = [
                "gopy",
                "pkg",
                "-name", "ohbother",
                "-output", os.path.join(project_root, "temp_out"),
                "-vm", python_path,
                "."
            ]
            print(f"Running gopy command from {os.getcwd()}: {' '.join(cmd)}")
            ret = subprocess.call(cmd, env=env, cwd=temp_dir)
            os.chdir(src_dir)  # ensure we're in src even after temp dir is removed

        # Change back to project root for output copying
        os.chdir(project_root)
        generated_dir = os.path.join("temp_out", "ohbother")
        if os.path.exists(generated_dir):
            for item in os.listdir(generated_dir):
                src_file = os.path.join(generated_dir, item)
                dst_file = os.path.join(ohbother_dir, item)
                if os.path.isfile(src_file):
                    shutil.copy2(src_file, dst_file)
                    print(f"Copied {src_file} to {dst_file}")

            go_dir = os.path.join("temp_out", "go")
            if os.path.exists(go_dir):
                ohbother_go_dir = os.path.join(ohbother_dir, "go")
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

        if os.path.exists("temp_out"):
            shutil.rmtree("temp_out")
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