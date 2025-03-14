//go:build windows

package ohbother

import (
	"fmt"
	"runtime"
	"syscall"

	"golang.org/x/sys/windows"
)

func PinToCPU(cpuID int) error {
	runtime.LockOSThread()

	// Get current thread handle (using the proper windows package function)
	currentThread := windows.CurrentThread()

	// Calculate the affinity mask for the specified CPU
	affinityMask := uintptr(1 << uint(cpuID))

	// Load kernel32.dll and find the SetThreadAffinityMask function
	// (since it's not directly exposed in the windows package)
	kernel32 := syscall.NewLazyDLL("kernel32.dll")
	setThreadAffinityMaskProc := kernel32.NewProc("SetThreadAffinityMask")

	// Set thread affinity mask
	ret, _, err := setThreadAffinityMaskProc.Call(uintptr(currentThread), affinityMask)
	if ret == 0 {
		return fmt.Errorf("failed to set thread affinity: %v", err)
	}

	return nil
}
