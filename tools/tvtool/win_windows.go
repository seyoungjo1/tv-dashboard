//go:build windows

package main

import (
	"os/exec"
	"syscall"
	"unsafe"
)

const createNoWindow = 0x08000000

func pythonName() string { return "pythonw.exe" }

// 내장 Python 을 창 없이 (pythonw 라 원래 창이 없지만, 혹시 python.exe 로 바뀌어도 검은 창이 뜨지 않게)
func hideWindow(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: createNoWindow}
}

// 오류는 작은 알림 창으로 (검은 창이 없으므로)
func showError(msg string) {
	user32 := syscall.NewLazyDLL("user32.dll")
	box := user32.NewProc("MessageBoxW")
	t, _ := syscall.UTF16PtrFromString(msg)
	c, _ := syscall.UTF16PtrFromString("직원 업로드")
	_, _, _ = box.Call(0, uintptr(unsafe.Pointer(t)), uintptr(unsafe.Pointer(c)), 0x10)
}
