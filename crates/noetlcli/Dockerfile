# Chef stage for dependency analysis
FROM lukemathwalker/cargo-chef:0.1.73-rust-1.81-alpine3.20 AS chef
WORKDIR /app
RUN apk update && \
    apk add --no-cache clang lld llvm musl-dev make pkgconfig openssl-dev openssl-libs-static

# Planner stage - analyzes dependencies
FROM chef AS planner
COPY . .
RUN cargo chef prepare --recipe-path recipe.json

# Builder stage - caches dependencies
FROM chef AS builder
COPY --from=planner /app/recipe.json recipe.json
RUN cargo chef cook --release --recipe-path recipe.json

# Build the application
COPY . .
RUN cargo build --release

# Runtime stage
FROM alpine:3.20 AS runtime
WORKDIR /app
RUN apk add --no-cache libgcc libxslt ca-certificates openssl
COPY --from=builder /app/target/release/noetlctl ./noetlctl

ENTRYPOINT ["./noetlctl"]
