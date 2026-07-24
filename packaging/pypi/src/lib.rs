//! PyO3 bindings for the NoETL CLI.
//!
//! Two entry points, both of which link the real thing rather than
//! reimplementing it:
//!
//! - [`cli_main`] hands an argv straight to `noetl::cli_main`, the clap
//!   dispatcher the `noetl` binary runs. Every subcommand works because it *is*
//!   the CLI.
//! - [`run_playbook`] drives `noetl::PlaybookRunner` — the local execution
//!   engine, dispatching steps through the `noetl-tools` registry — and returns
//!   the `RunOutcome` as JSON so Python can hand back a dict.

use std::collections::HashMap;
use std::path::PathBuf;

use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;

/// Build the multi-thread Tokio runtime the CLI expects.
///
/// Not an implementation detail we get to choose: the local engine reaches
/// `tokio::task::block_in_place` for the tool bridge, which panics on a
/// current-thread runtime. `#[tokio::main]` gave the binary a multi-thread
/// runtime and this reproduces it.
fn tokio_runtime() -> PyResult<tokio::runtime::Runtime> {
    tokio::runtime::Runtime::new()
        .map_err(|err| PyRuntimeError::new_err(format!("failed to start the async runtime: {err}")))
}

/// Run the CLI with `argv` and return its exit code.
///
/// `argv` includes the program name at index 0, as a real argv does. Output
/// goes to the process's own stdout/stderr — this is the CLI, so it renders
/// the same text it always did.
#[pyfunction]
#[pyo3(signature = (argv))]
fn cli_main(py: Python<'_>, argv: Vec<String>) -> i32 {
    // The CLI blocks on network and disk; holding the GIL through it would
    // freeze every other Python thread.
    py.detach(|| noetl::cli_main(argv))
}

/// Execute a playbook locally and return its `RunOutcome` as a JSON string.
///
/// The caller-facing wrapper in `noetl/__init__.py` parses this into a dict; the
/// binding stays at JSON so the envelope shape is owned by the Rust
/// `RunOutcome` type and cannot drift on the Python side.
#[pyfunction]
#[pyo3(signature = (playbook, variables=None, target=None, verbose=false, quiet=true, facts_out=None, merge=false))]
#[allow(clippy::too_many_arguments)]
fn run_playbook(
    py: Python<'_>,
    playbook: PathBuf,
    variables: Option<HashMap<String, String>>,
    target: Option<String>,
    verbose: bool,
    quiet: bool,
    facts_out: Option<PathBuf>,
    merge: bool,
) -> PyResult<String> {
    if !playbook.exists() {
        return Err(PyValueError::new_err(format!(
            "playbook not found: {}",
            playbook.display()
        )));
    }

    py.detach(move || {
        let runner = noetl::PlaybookRunner::new(playbook)
            .with_variables(variables.unwrap_or_default())
            .with_target(target)
            .with_verbose(verbose)
            .with_quiet(quiet)
            .with_merge(merge)
            .with_facts_out(facts_out)
            // The envelope comes back through the return value; printing it to
            // stdout as well would corrupt any caller piping this process.
            .with_emit_json(false);

        let runtime = tokio_runtime()?;
        let outcome = runtime
            .block_on(async { runner.run() })
            .map_err(|err| PyRuntimeError::new_err(format!("{err:?}")))?;

        serde_json::to_string(&outcome)
            .map_err(|err| PyRuntimeError::new_err(format!("failed to serialise RunOutcome: {err}")))
    })
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    module.add_function(wrap_pyfunction!(cli_main, module)?)?;
    module.add_function(wrap_pyfunction!(run_playbook, module)?)?;
    Ok(())
}
