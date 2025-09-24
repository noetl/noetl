# control_flow_workbook

Verifies:
- `next` with `when:` conditions selects the correct branch.
- Multiple `next` targets **without** `when` run in **parallel**.
- `type: workbook` step resolves to a workbook action by `name`.

Tweak `workload.temperature_c` to flip the branch (>=25 → hot).

## Testing

### Static Tests (Default)
```bash
make test-control-flow-workbook
```
Tests playbook parsing, planning, and structural validation without runtime execution.

### Runtime Tests (Optional)
```bash
# With running server
make test-control-flow-workbook-runtime

# Full integration (reset DB, restart server, run tests)
make test-control-flow-workbook-full
```
Tests actual execution through the noetl server API, including:
- Real conditional branching evaluation
- Parallel step execution
- Workbook action resolution and execution