"""
NoETL DSL Core Models - Canonical v10 Format

Canonical v10 implementation with:
- `when` is the ONLY conditional keyword (no `expr`)
- All knobs live under `spec` (at any level)
- Policies live under `spec.policy` and are typed by scope
- Task output-status handling uses `task.spec.policy` object with required `rules:`
- Routing uses Petri-net arcs: `step.next` is object with `next.spec` + `next.arcs[]`
- No special "sink" tool kind - storage is just tools returning references
- Loop is a step modifier (not a tool kind)
- NO `step.when` field - step admission via `step.spec.policy.admit.rules`
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Any, Literal, Optional, Union
from datetime import datetime


# ============================================================================
# Event Payload Models - Typed payloads for different event types
# ============================================================================



__all__ = [name for name in globals() if not name.startswith("__")]
