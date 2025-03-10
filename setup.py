import os
import sys
import glob
import setuptools
from setuptools import Extension

version = "0.0.2"

# Read long description from README
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

# Find the appropriate extension files based on platform
ext_modules = []

# More robust file finding - look for all shared libraries recursively
def find_shared_libraries(base_dir, pattern):
    matches = []
    for root, dirnames, filenames in os.walk(base_dir):
        for filename in filenames:
            if any(filename.endswith(ext) for ext in pattern):
                matches.append(os.path.join(root, filename))
    return matches

# Look for compiled extension files
if sys.platform.startswith('darwin'):  # macOS
    so_files = glob.glob('ohbother/generated/_ohbother.cpython-*.so') or \
               find_shared_libraries('ohbother/generated', ['.so', '.dylib'])
    if so_files:
        ext_modules.append(
            Extension(
                name='ohbother.generated._ohbother',
                sources=['ohbother/generated/ohbother.c'],  # Source file is already compiled
                py_limited_api=False,
            )
        )
elif sys.platform.startswith('win'):  # Windows
    dll_files = glob.glob('ohbother/generated/_ohbother.*.pyd') or \
                glob.glob('ohbother/generated/_ohbother.*.dll') or \
                find_shared_libraries('ohbother/generated', ['.pyd', '.dll'])
    if dll_files:
        ext_modules.append(
            Extension(
                name='ohbother.generated._ohbother',
                sources=['ohbother/generated/ohbother.c'],  # Source file is already compiled
                py_limited_api=False,
            )
        )
elif sys.platform.startswith('linux'):  # Linux
    so_files = glob.glob('ohbother/generated/_ohbother.cpython-*.so') or \
               find_shared_libraries('ohbother/generated', ['.so'])
    if so_files:
        ext_modules.append(
            Extension(
                name='ohbother.generated._ohbother',
                sources=['ohbother/generated/ohbother.c'],  # Source file is already compiled
                py_limited_api=False,
            )
        )

setuptools.setup(
    name="ohbother",
    version=version,
    author="ppoage",
    description="High-performance packet processing library",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/ohbother",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    package_dir={"": "."},
    packages=setuptools.find_packages(where="."),
    include_package_data=True,
    python_requires=">=3.10",
    ext_modules=ext_modules,  # Add extension modules to mark as binary wheel
    # package_data section that includes EVERYTHING in generated and all subdirectories
    package_data={
        "ohbother.generated": ["*", "*/*", "*/*/*"],  # Include everything in the generated directory and subdirectories
    }

)