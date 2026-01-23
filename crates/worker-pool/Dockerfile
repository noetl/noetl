# Chef stage for dependency analysis
# https://crates.io/crates/cargo-chef/0.1.73
FROM lukemathwalker/cargo-chef:0.1.73-rust-1.91.1-alpine3.22 AS chef
WORKDIR /app
RUN apk update && \
    apk add --no-cache clang lld llvm musl-dev make pkgconfig openssl-dev openssl-libs-static

# Planner stage - analyzes dependencies
FROM chef AS planner
COPY . .
# Compute a lock-like file for dependency installation
RUN cargo chef prepare --recipe-path recipe.json

# Builder stage - caches dependencies
FROM chef AS builder
COPY --from=planner /app/recipe.json recipe.json
# Build dependencies - this layer is cached as long as Cargo.toml/Cargo.lock don't change
RUN cargo chef cook --release --recipe-path recipe.json

# Build the application
COPY . .
RUN cargo build --release --bin noetl-worker

# Runtime stage
FROM alpine:3.22.2 AS runtime

WORKDIR /app

# Install necessary runtime dependencies
RUN apk add --no-cache libgcc libxslt ca-certificates openssl python3 py3-pip

# Copy the compiled binary
COPY --from=builder /app/target/release/noetl-worker ./noetl-worker

# Default environment variables
ENV WORKER_POOL_NAME=worker-rust-pool \
    NOETL_SERVER_URL=http://noetl.noetl.svc.cluster.local:8082 \
    NATS_URL=nats://nats.nats.svc.cluster.local:4222 \
    NATS_STREAM=NOETL_COMMANDS \
    NATS_CONSUMER=noetl_worker_pool \
    WORKER_HEARTBEAT_INTERVAL=15 \
    WORKER_MAX_CONCURRENT=4 \
    RUST_LOG=info,worker_pool=debug

ENTRYPOINT ["./noetl-worker"]
