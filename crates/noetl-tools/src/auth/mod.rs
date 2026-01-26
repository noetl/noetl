//! Authentication module.
//!
//! Provides authentication resolvers for various auth methods:
//! - GCP Application Default Credentials
//! - Bearer token
//! - Basic auth
//! - API key

mod gcp;
mod resolver;

pub use gcp::GcpAuth;
pub use resolver::{AuthCredentials, AuthResolver};
