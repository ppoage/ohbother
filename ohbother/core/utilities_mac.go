//go:build !windows && !linux

package ohbother

import (
	"runtime"
)

func PinToCPU(cpuID int) error {
	runtime.LockOSThread()

	// Just log that pinning isn't supported on this platform
	if runtime.GOOS == "darwin" {
		LogInfo("CPU pinning not supported on macOS, thread is locked but not pinned to core %d", cpuID)
	} else {
		LogInfo("CPU pinning not supported on %s, thread is locked but not pinned", runtime.GOOS)
	}
	return nil
}
