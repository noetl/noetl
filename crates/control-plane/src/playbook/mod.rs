//! NoETL Playbook DSL v2.
//!
//! This module provides playbook parsing and validation:
//! - Type definitions for playbook structure
//! - YAML parsing
//! - Validation

pub mod parser;
pub mod types;

pub use parser::{extract_kind, extract_metadata, parse_playbook, validate_playbook};
pub use types::{
    CaseEntry, Command, KeychainDef, Loop, LoopMode, Metadata, NextSpec, NextTarget, Playbook,
    Step, ToolCall, ToolKind, ToolSpec, WorkbookTask,
};
