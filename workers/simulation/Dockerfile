# ==========================================
# Stage 1: Builder C++ (build HiGHS + build solver)
# ==========================================
FROM python:3.10-slim AS builder

ARG HIGHS_TAG=v1.13.0

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    ninja-build \
    ca-certificates \
    libc-bin \
  && rm -rf /var/lib/apt/lists/*

# BUILD SOLVER + HIGHS
RUN set -eux; \
  git clone --depth 1 --branch "${HIGHS_TAG}" https://github.com/ERGO-Code/HiGHS.git /tmp/HiGHS; \
  cmake -S /tmp/HiGHS -B /tmp/HiGHS/build -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=ON \
    -DCMAKE_INSTALL_PREFIX=/usr/local; \
  cmake --build /tmp/HiGHS/build; \
  cmake --install /tmp/HiGHS/build; \
  ldconfig; \
  ls -la /usr/local/lib | grep -i highs

WORKDIR /build
COPY solver/ ./solver/

RUN rm -rf solver/pipeline/build && \
    chmod +x solver/build_pipeline.sh && \
    ./solver/build_pipeline.sh

RUN set -eux; \
  SOLVER="/build/solver/pipeline/build/solver_cpp"; \
  test -x "$SOLVER"; \
  echo "--- ldd solver_cpp (builder) ---"; \
  ldd "$SOLVER"; \
  mkdir -p /libs_export; \
  cp -L /usr/local/lib/libhighs.so* /libs_export/; \
  cd /libs_export; \
  if [ ! -e libhighs.so.1 ]; then \
    v="$(ls -1 libhighs.so.1.* 2>/dev/null | head -n 1 || true)"; \
    if [ -n "$v" ]; then ln -s "$v" libhighs.so.1; \
    elif [ -e libhighs.so ]; then ln -s libhighs.so libhighs.so.1; \
    else echo "FATAL: cannot create libhighs.so.1"; exit 1; \
    fi; \
  fi; \
  ls -la libhighs.so*

# ==========================================
# Stage 2: Runtime Python
# ==========================================
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV LD_LIBRARY_PATH=/usr/local/lib:/usr/lib:/lib:$LD_LIBRARY_PATH

WORKDIR /app

# Aggiunti gcc e python3-dev per permettere a pip di compilare i wheels su ARM64
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    libgomp1 \
    libstdc++6 \
    libgcc-s1 \
    ca-certificates \
    libc-bin \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /app/solver_bin
COPY --from=builder /build/solver/pipeline/build/solver_cpp /app/solver_bin/solver_cpp

COPY --from=builder /libs_export/ /usr/local/lib/

RUN set -eux; \
  echo "/usr/local/lib" > /etc/ld.so.conf.d/local.conf; \
  ldconfig; \
  echo "--- runtime highs check ---"; \
  ls -la /usr/local/lib | grep -i highs; \
  echo "--- ldd solver_cpp (runtime) ---"; \
  ldd /app/solver_bin/solver_cpp; \
  ! ldd /app/solver_bin/solver_cpp | grep -q "not found"

COPY worker.py .
COPY preprocessing/ ./preprocessing/
COPY solver/runner.py ./solver/runner.py

RUN mkdir -p /app/data/agora_models && \
    mkdir -p /app/temp_work

CMD ["python", "worker.py"]