//go:build linux

package utils

import (
	"runtime"
	"syscall"
	"unsafe"
)

func PinToCPU(cpuID int) error {
	runtime.LockOSThread()

	var mask uint64 = 1 << uint(cpuID)
	_, _, errno := syscall.Syscall(syscall.SYS_SCHED_SETAFFINITY, 0,
		unsafe.Sizeof(mask), uintptr(unsafe.Pointer(&mask)))
	if errno != 0 {
		return errno
	}
	return nil
}
