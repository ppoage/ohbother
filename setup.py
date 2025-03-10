import os
import setuptools

version = "0.0.2"

# Read long description from README
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="ohbother",
    version=version,
    author="ppoage",
    description="High-performance packet processing library",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/ohbother",
    project_urls={
        "Bug Tracker": "https://github.com/yourusername/ohbother/issues",
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    package_dir={"": "."},
    packages=setuptools.find_packages(where="."),
    include_package_data=True,
    python_requires=">=3.10",
)