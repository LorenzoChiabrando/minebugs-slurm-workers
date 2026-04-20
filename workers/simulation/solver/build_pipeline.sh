#!/bin/bash

echo "[BUILD] Starting Solver Compilation..."

cd "$(dirname "$0")/pipeline"

mkdir -p build

cmake -S . -B build -DCMAKE_BUILD_TYPE=Release

cmake --build build --config Release --parallel $(nproc)

echo "[BUILD] Success! Binary created at: $(pwd)/build/solver_cpp"