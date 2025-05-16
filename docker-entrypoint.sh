#!/bin/bash
set -e

echo "Starting Xvfb..."

# Clean up any existing lock files to avoid "server already running" errors
if [ -f "/tmp/.X1-lock" ]; then
  echo "Removing existing X lock file"
  rm -f /tmp/.X1-lock
fi
if [ -d "/tmp/.X11-unix/X1" ]; then
  echo "Removing existing X11 socket"
  rm -f /tmp/.X11-unix/X1
fi

# Start Xvfb with error handling
Xvfb :1 -screen 0 3840x2160x24 &
export DISPLAY=:1

# Wait a moment for Xvfb to initialize
sleep 2

# Check if arguments were provided, if not, use default command
if [ $# -eq 0 ]; then
  echo "No command provided, using default: python -m vidx"
  exec python -m vidx
else
  echo "Executing command: $@"
  exec "$@"
fi