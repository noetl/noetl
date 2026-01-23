//! Cryptography module for the NoETL Control Plane.
//!
//! Provides AES-GCM encryption for credential data.

pub mod encryption;

pub use encryption::{decrypt, encrypt, Encryptor};
