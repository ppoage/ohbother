import faulthandler
faulthandler.enable()

print("Before import")
try:
    # import sys, os
    # sys.setdlopenflags(0x100 | 0x2)  # RTLD_GLOBAL | RTLD_NOW
    import ohbother
    print("Import succeeded")
except Exception as e:
    print(f"Exception: {e}")