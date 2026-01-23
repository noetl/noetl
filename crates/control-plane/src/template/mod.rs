//! Template rendering module.
//!
//! Provides Jinja2-style template rendering for NoETL playbooks.

pub mod jinja;

pub use jinja::TemplateRenderer;
