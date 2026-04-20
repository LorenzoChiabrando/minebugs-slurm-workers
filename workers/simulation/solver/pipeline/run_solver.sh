#!/bin/bash
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BUILD_DIR="$SCRIPT_DIR/build"
BIN_NAME="solver_cpp"
EXECUTABLE="$BUILD_DIR/$BIN_NAME"

if [ ! -f "$EXECUTABLE" ] || [ "$1" == "--rebuild" ]; then
    echo "[WRAPPER] Compiling Solver..."
    mkdir -p "$BUILD_DIR"
    
    cmake -S "$SCRIPT_DIR" -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE=Release
    

    cmake --build "$BUILD_DIR" --config Release --parallel $(nproc)
    echo "[WRAPPER] Compilation complete."
    

    if [ "$1" == "--rebuild" ]; then exit 0; fi
fi

echo "[WRAPPER] Running Solver..."
"$EXECUTABLE" "$@"
