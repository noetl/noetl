//! NATS JetStream integration for NoETL Control Plane.
//!
//! Provides command notification publishing to workers via NATS JetStream.

pub mod publisher;

pub use publisher::NatsPublisher;
