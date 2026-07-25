#!/bin/bash
# Bash CLI Wrapper for IPAM Test Suite

# Identify python command
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "Error: Python is not installed or not in PATH."
    exit 1
fi

$PYTHON_CMD run_tests.py "$@"
exit $?
