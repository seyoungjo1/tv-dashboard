//go:build !windows

package main

import (
	"fmt"
	"os"
	"os/exec"
)

// Windows 가 아닌 곳(시험용): app/python/python3 (또는 심볼릭 링크)

func pythonName() string { return "python3" }

func hideWindow(cmd *exec.Cmd) {}

func showError(msg string) { fmt.Fprintln(os.Stderr, msg) }
