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
    CanonicalNextTarget, Command, EvalCondition, EvalElse, EvalEntry, KeychainDef, Loop, LoopMode,
    LoopSpec, Metadata, NextSpec, Playbook, Step, StepSpec, ToolCall, ToolDefinition, ToolKind,
    ToolSpec, WorkbookTask,
};
