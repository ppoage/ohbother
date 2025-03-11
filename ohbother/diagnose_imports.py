# ADD: new file ohbother/diagnose_imports.py

#!/usr/bin/env python3
"""
Diagnostic utility to check what functions are exported from the generated Go code.

This helps identify issues with import paths for optimized functions.
"""

import sys
import os
import inspect

def inspect_module(module_name):
    """Inspect a module and print its contents"""
    try:
        module = __import__(module_name, fromlist=['*'])
        print(f"\nModule: {module_name}")
        print(f"File: {getattr(module, '__file__', 'Unknown')}")
        print("Contents:")
        for name in dir(module):
            if not name.startswith('_'):  # Skip private attributes
                value = getattr(module, name)
                if inspect.ismodule(value):
                    print(f"  {name}: <module>")
                elif inspect.isfunction(value) or inspect.isbuiltin(value):
                    print(f"  {name}: <function>")
                elif inspect.isclass(value):
                    print(f"  {name}: <class>")
                else:
                    print(f"  {name}: {type(value)}")
        print()
    except ImportError as e:
        print(f"Error importing {module_name}: {e}")
    except Exception as e:
        print(f"Error inspecting {module_name}: {e}")

def main():
    """Run diagnostics on ohbother modules"""
    print(f"Python version: {sys.version}")
    print(f"Python path: {sys.path}")
    
    # Check main ohbother module
    inspect_module('ohbother')
    
    # Check generated module
    inspect_module('ohbother.generated')
    
    # Try potential locations for the Go functions
    modules_to_check = [
        'ohbother.generated.ohbother',
        'ohbother.generated.go',
        'ohbother.generated.utils',
    ]
    
    for module in modules_to_check:
        inspect_module(module)
    
    # Check if BatchConvertBytesToSlices is available
    print("\nSearching for BatchConvertBytesToSlices function:")
    found = False
    
    try:
        from ohbother.generated import BatchConvertBytesToSlices
        print("✓ Found in ohbother.generated")
        found = True
    except ImportError:
        print("✗ Not found in ohbother.generated")
    
    try:
        from ohbother.generated.ohbother import BatchConvertBytesToSlices
        print("✓ Found in ohbother.generated.ohbother")
        found = True
    except ImportError:
        print("✗ Not found in ohbother.generated.ohbother")
        
    try:
        from ohbother.generated.go import BatchConvertBytesToSlices
        print("✓ Found in ohbother.generated.go")
        found = True
    except ImportError:
        print("✗ Not found in ohbother.generated.go")
        
    if not found:
        print("\n⚠️ BatchConvertBytesToSlices function not found in any module!")
        print("This explains why optimized batch conversion is not available.")

if __name__ == "__main__":
    main()