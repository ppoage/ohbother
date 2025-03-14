//go:build !windows && !linux

package utils

import (
	"ohbother/src/config"
	"runtime"
)

func PinToCPU(cpuID int) error {
	runtime.LockOSThread()

	// Just log that pinning isn't supported on this platform
	if runtime.GOOS == "darwin" {
		config.LogInfo("CPU pinning not supported on macOS, thread is locked but not pinned to core %d", cpuID)
	} else {
		config.LogInfo("CPU pinning not supported on %s, thread is locked but not pinned", runtime.GOOS)
	}
	return nil
}
