//! Workflow execution engine.
//!
//! This module provides the core execution engine for NoETL:
//!
//! - **Orchestrator**: Coordinates workflow execution flow
//! - **State**: Reconstructs execution state from events
//! - **Evaluator**: Evaluates conditions and case/when/then logic
//! - **Commands**: Generates commands for workers

pub mod commands;
pub mod evaluator;
pub mod orchestrator;
pub mod state;

pub use commands::{Command, CommandBuilder};
pub use evaluator::ConditionEvaluator;
pub use orchestrator::WorkflowOrchestrator;
pub use state::{ExecutionState, StepState, WorkflowState};
