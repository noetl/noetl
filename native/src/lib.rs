use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use std::time::Instant;

use anyhow::{anyhow, bail, Context, Result};
use noetl_executor::playbook::{CmdsList, Playbook, Tool};
use noetl_tools::context::ExecutionContext;
use noetl_tools::registry::ToolConfig;
use noetl_tools::result::ToolStatus;
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use serde::Serialize;
use serde_json::{json, Value};

const VERSION: &str = "5.0.0";

#[derive(Debug, Serialize)]
struct StepOutcome {
    step: String,
    status: String,
    result: Value,
}

#[derive(Debug, Serialize)]
struct RunOutcome {
    status: String,
    playbook_name: String,
    playbook_path: String,
    runtime: String,
    runtime_provenance: String,
    started_at: String,
    completed_at: String,
    duration_seconds: f64,
    executed_steps: Vec<String>,
    step_results: Vec<StepOutcome>,
    final_result: Option<Value>,
    error: Option<String>,
}

#[pyfunction]
fn version() -> &'static str {
    VERSION
}

#[pyfunction]
fn registered_tools() -> Vec<String> {
    let mut names = noetl_tools::tools::create_default_registry()
        .list()
        .into_iter()
        .map(str::to_string)
        .collect::<Vec<_>>();
    names.sort();
    names
}

#[pyfunction]
#[pyo3(signature = (playbook, runtime=None, target=None, variables=None, json_output=false, verbose=false))]
fn run(
    playbook: String,
    runtime: Option<String>,
    target: Option<String>,
    variables: Option<HashMap<String, String>>,
    json_output: bool,
    verbose: bool,
) -> PyResult<String> {
    run_inner(
        PathBuf::from(playbook),
        runtime.as_deref().unwrap_or("auto"),
        target,
        variables.unwrap_or_default(),
        json_output,
        verbose,
    )
    .map_err(|err| PyRuntimeError::new_err(err.to_string()))
}

#[pyfunction]
#[pyo3(signature = (argv))]
fn cli_main(argv: Vec<String>) -> PyResult<i32> {
    if argv.is_empty() || argv.iter().any(|arg| arg == "--help" || arg == "-h") {
        print_help();
        return Ok(0);
    }

    let mut args = argv.into_iter();
    let command = args
        .next()
        .ok_or_else(|| PyValueError::new_err("missing command"))?;
    let alias = matches!(command.as_str(), "exec" | "execute");
    if !matches!(command.as_str(), "run" | "exec" | "execute") {
        return Err(PyValueError::new_err(format!(
            "unsupported command '{command}' in the Python wheel; use 'noetl run'"
        )));
    }
    if alias {
        eprintln!("Warning: 'noetl {command}' is deprecated; use 'noetl run' instead.");
    }

    let mut playbook = None;
    let mut runtime = "auto".to_string();
    let mut target = None;
    let mut variables = HashMap::new();
    let mut json_output = false;
    let mut verbose = false;

    let mut rest = args.peekable();
    while let Some(arg) = rest.next() {
        match arg.as_str() {
            "-r" | "--runtime" => {
                runtime = rest
                    .next()
                    .ok_or_else(|| PyValueError::new_err("--runtime requires a value"))?;
            }
            "-t" | "--target" => {
                target = Some(
                    rest.next()
                        .ok_or_else(|| PyValueError::new_err("--target requires a value"))?,
                );
            }
            "--set" => {
                let raw = rest
                    .next()
                    .ok_or_else(|| PyValueError::new_err("--set requires KEY=VALUE"))?;
                let (key, value) = raw
                    .split_once('=')
                    .ok_or_else(|| PyValueError::new_err("--set requires KEY=VALUE"))?;
                variables.insert(key.to_string(), value.to_string());
            }
            "--json" | "-j" => json_output = true,
            "--verbose" | "-v" => verbose = true,
            value if value.starts_with('-') => {
                return Err(PyValueError::new_err(format!(
                    "unsupported option '{value}'"
                )));
            }
            value => {
                if playbook.is_some() {
                    return Err(PyValueError::new_err(format!(
                        "unexpected extra argument '{value}'"
                    )));
                }
                playbook = Some(value.to_string());
            }
        }
    }

    let playbook = playbook.ok_or_else(|| PyValueError::new_err("missing playbook path"))?;
    let outcome = run_inner(
        PathBuf::from(playbook),
        &runtime,
        target,
        variables,
        json_output,
        verbose,
    )
    .map_err(|err| PyRuntimeError::new_err(err.to_string()))?;

    if json_output {
        println!("{outcome}");
    } else {
        let parsed: Value = serde_json::from_str(&outcome)
            .map_err(|err| PyRuntimeError::new_err(err.to_string()))?;
        let status = parsed
            .get("status")
            .and_then(Value::as_str)
            .unwrap_or("unknown");
        let name = parsed
            .get("playbook_name")
            .and_then(Value::as_str)
            .unwrap_or("playbook");
        println!("{name}: {status}");
        if let Some(final_result) = parsed.get("final_result") {
            if !final_result.is_null() {
                println!(
                    "{}",
                    serde_json::to_string_pretty(final_result).unwrap_or_default()
                );
            }
        }
    }
    Ok(0)
}

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(registered_tools, m)?)?;
    m.add_function(wrap_pyfunction!(run, m)?)?;
    m.add_function(wrap_pyfunction!(cli_main, m)?)?;
    Ok(())
}

fn run_inner(
    playbook_path: PathBuf,
    runtime: &str,
    target: Option<String>,
    variables: HashMap<String, String>,
    json_output: bool,
    verbose: bool,
) -> Result<String> {
    let (effective_runtime, provenance) = resolve_runtime(runtime)?;
    if effective_runtime != "local" {
        bail!("the Python wheel currently supports only --runtime local");
    }

    eprintln!("Runtime: {effective_runtime} ({provenance})");

    let started_at = chrono::Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string();
    let start = Instant::now();

    let content = fs::read_to_string(&playbook_path)
        .with_context(|| format!("failed to read playbook {}", playbook_path.display()))?;
    let playbook: Playbook =
        serde_yaml::from_str(&content).context("failed to parse playbook YAML")?;
    let selected_steps = select_steps(&playbook, target.as_deref())?;

    let rt = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .context("failed to create Tokio runtime")?;

    let mut step_results = Vec::new();
    let mut final_result = None;
    let registry = noetl_tools::tools::create_default_registry();
    let mut context_vars = initial_context_vars(&playbook, &variables)?;

    for step in selected_steps {
        if verbose {
            eprintln!("Running step: {}", step.step);
        }
        let Some(tool) = &step.tool else {
            continue;
        };
        let config = tool_config(tool)?;
        let mut ctx = ExecutionContext::new(0, step.step.clone(), "");
        ctx.merge_variables(&context_vars);

        let result = rt
            .block_on(registry.execute_from_config(&config, &ctx))
            .with_context(|| format!("step '{}' failed", step.step))?;
        if result.status != ToolStatus::Success {
            bail!(
                "step '{}' returned {}: {}",
                step.step,
                result.status,
                result.error.unwrap_or_else(|| "tool error".to_string())
            );
        }

        let result_value = serde_json::to_value(&result)?;
        context_vars.insert(step.step.clone(), result_value.clone());
        final_result = Some(result_value.clone());
        step_results.push(StepOutcome {
            step: step.step.clone(),
            status: result.status.to_string(),
            result: result_value,
        });
    }

    let completed_at = chrono::Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string();
    let outcome = RunOutcome {
        status: "ok".to_string(),
        playbook_name: playbook.metadata.name,
        playbook_path: playbook_path.display().to_string(),
        runtime: effective_runtime,
        runtime_provenance: provenance,
        started_at,
        completed_at,
        duration_seconds: start.elapsed().as_secs_f64(),
        executed_steps: step_results.iter().map(|item| item.step.clone()).collect(),
        step_results,
        final_result,
        error: None,
    };

    if json_output {
        Ok(serde_json::to_string_pretty(&outcome)?)
    } else {
        Ok(serde_json::to_string(&outcome)?)
    }
}

fn resolve_runtime(runtime: &str) -> Result<(String, String)> {
    match runtime {
        "local" => Ok(("local".to_string(), "from --runtime flag".to_string())),
        "auto" | "" => Ok(("local".to_string(), "local default".to_string())),
        "distributed" => Ok(("distributed".to_string(), "from --runtime flag".to_string())),
        other => bail!("unknown runtime '{other}'. Use local, distributed, or auto"),
    }
}

fn select_steps<'a>(
    playbook: &'a Playbook,
    target: Option<&str>,
) -> Result<Vec<&'a noetl_executor::playbook::Step>> {
    if let Some(target) = target {
        let pos = playbook
            .workflow
            .iter()
            .position(|step| step.step == target)
            .ok_or_else(|| anyhow!("target step '{target}' was not found"))?;
        Ok(playbook.workflow[pos..].iter().collect())
    } else {
        Ok(playbook.workflow.iter().collect())
    }
}

fn initial_context_vars(
    playbook: &Playbook,
    variables: &HashMap<String, String>,
) -> Result<HashMap<String, Value>> {
    let mut values = HashMap::new();
    let mut workload_obj = serde_json::Map::new();
    if let Some(workload) = &playbook.workload {
        for (key, value) in workload {
            let json_value = serde_json::to_value(value)?;
            values.insert(key.clone(), json_value.clone());
            values.insert(format!("workload.{key}"), json_value);
            workload_obj.insert(key.clone(), serde_json::to_value(value)?);
        }
    }
    for (key, value) in variables {
        values.insert(key.clone(), json!(value));
        if !key.starts_with("workload.") {
            values.insert(format!("workload.{key}"), json!(value));
            workload_obj.insert(key.clone(), json!(value));
        } else if let Some(stripped) = key.strip_prefix("workload.") {
            workload_obj.insert(stripped.to_string(), json!(value));
        }
    }
    values.insert("workload".to_string(), Value::Object(workload_obj));
    Ok(values)
}

fn tool_config(tool: &Tool) -> Result<ToolConfig> {
    match tool {
        Tool::Shell { cmds } => {
            let command = match cmds {
                CmdsList::Single(cmd) => cmd.clone(),
                CmdsList::Multiple(cmds) => cmds.join("\n"),
            };
            Ok(ToolConfig {
                kind: "shell".to_string(),
                config: json!({ "command": command }),
                timeout: None,
                retry: None,
                auth: None,
            })
        }
        Tool::Rhai { code, args } => Ok(ToolConfig {
            kind: "rhai".to_string(),
            config: json!({ "code": code, "args": args }),
            timeout: None,
            retry: None,
            auth: None,
        }),
        Tool::Http {
            method,
            url,
            headers,
            params,
            body,
            auth: _,
        } => Ok(ToolConfig {
            kind: "http".to_string(),
            config: json!({
                "method": method,
                "url": url,
                "headers": headers,
                "params": params,
                "body": body,
            }),
            timeout: None,
            retry: None,
            auth: None,
        }),
        Tool::DuckDb { .. } => bail!(
            "kind: duckdb is not enabled in the default pip wheel; rebuild with noetl-tools/duckdb-integration for DuckDB local-mode support"
        ),
        Tool::Playbook { .. } => bail!(
            "nested kind: playbook is not implemented in the first PyO3 CLI wheel"
        ),
        Tool::Auth { .. } => bail!("kind: auth is not implemented in the first PyO3 CLI wheel"),
        Tool::Sink { .. } => bail!("kind: sink is not implemented in the first PyO3 CLI wheel"),
        Tool::Unsupported => bail!("unsupported tool kind"),
    }
}

fn print_help() {
    println!(
        "NoETL CLI (Python/Rust bindings)\n\nUSAGE:\n    noetl run <PLAYBOOK> [--runtime local] [--set KEY=VALUE] [--json]\n\nCOMMANDS:\n    run       Execute a playbook locally (canonical)\n    exec      Deprecated alias for run\n    execute   Deprecated alias for run\n\nNOTES:\n    This pip wheel is CLI-only. Server, worker, and gateway ship as Rust services via ops.\n    DuckDB local-mode support is not compiled into the default wheel."
    );
}
