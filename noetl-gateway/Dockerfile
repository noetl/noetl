# syntax=docker/dockerfile:1

FROM rust:1.83 as builder
WORKDIR /app

# Cache deps
COPY Cargo.toml ./
RUN mkdir -p src && echo "fn main(){}" > src/main.rs
RUN cargo build --release || true

# Build
COPY src ./src
RUN cargo build --release

FROM gcr.io/distroless/cc-debian12:nonroot
WORKDIR /app
COPY --from=builder /app/target/release/noetl-graphql-router /app/noetl-graphql-router
ENV ROUTER_PORT=8090
EXPOSE 8090
USER nonroot
ENTRYPOINT ["/app/noetl-graphql-router"]
