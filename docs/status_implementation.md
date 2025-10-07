# Status Normalization Implementation Summary

## Overview
This implementation enforces strict status validation across the NoETL event system, ensuring all events use normalized uppercase statuses (`STARTED`, `RUNNING`, `PAUSED`, `PENDING`, `FAILED`, `COMPLETED`) instead of the previous approach of normalizing mixed-case statuses at the end.

## Changes Made

### 1. Core Status Validation Module (`noetl/core/status.py`)
- **New file** providing centralized status validation
- Defines canonical uppercase status values: `STARTED`, `RUNNING`, `PAUSED`, `PENDING`, `FAILED`, `COMPLETED`
- Provides `validate_status()` to strictly validate against canonical values
- Provides `normalize_status()` to convert legacy statuses to canonical ones
- Provides `is_valid_status()` for non-exception checking

### 2. Event Service (`noetl/api/routers/event/service.py`)
- strict status validation in `emit()` method that raises `ValueError` for invalid statuses
- status handling to use uppercase canonical values throughout
- fallback normalization for legacy data with warning logs

### 3. Worker (`noetl/worker/worker.py`)
- all event generation to use uppercase statuses:
  - `action_started` events use `STARTED`
  - `action_completed` events use `COMPLETED` 
  - `action_error` events use `FAILED`
  - `step_result` events use `COMPLETED`
- `_validate_event_status()` method to validate events before sending
- status validation to all `report_event()` calls
- import for `validate_status` function

### 4. Execution API (`noetl/api/routers/event/executions.py`)
- handle uppercase statuses in execution status logic
- fallback normalization for legacy data with warning logs
- progress calculation to work with all 6 statuses

### 5. Broker Execute (`noetl/api/routers/broker/execute.py`)
- `execution_start` events to use canonical `STARTED` status
- all event generation to use normalized statuses

## Status Definitions

### Comprehensive 6-Status System
The new system provides clear, unambiguous statuses for all scenarios:

- **`STARTED`** - Initial state when execution/action begins
- **`RUNNING`** - Actively executing/processing
- **`PAUSED`** - Temporarily suspended but can resume
- **`PENDING`** - Waiting to start or queued
- **`FAILED`** - Execution failed with errors
- **`COMPLETED`** - Successfully finished

### Status Transitions
- `PENDING` → `STARTED` → `RUNNING` → `COMPLETED`
- `PENDING` → `STARTED` → `RUNNING` → `FAILED`
- `RUNNING` ⇄ `PAUSED` (bidirectional)

### Canonical Status Values  
- **All events MUST use canonical uppercase statuses**: `STARTED`, `RUNNING`, `PAUSED`, `PENDING`, `FAILED`, `COMPLETED`
- **Invalid statuses cause immediate failure** with clear error messages
- **Legacy data is normalized with warning logs** to identify sources that need fixing
- **Consistent status representation** throughout the entire system
- **6 comprehensive statuses** cover all execution scenarios

## Error Handling
- Invalid statuses in new events cause `ValueError` with descriptive messages listing valid statuses
- Workers will fail and stop execution if they try to generate invalid statuses
- Legacy data is handled gracefully with normalization and warning logs
- Clear error messages help identify and fix status generation issues

## Testing
- Added test script (`test_status_validation.py`) 
- Tests all validation functions and edge cases including new statuses
- Verifies integration with EventService
- All tests pass successfully
