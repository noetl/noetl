"""
Event control package.
Routes persisted events to specialized controllers (playbook, step, loop, action, workbook)
for orchestration decisions (enqueue next work, finalize results, etc.).
"""

from .dispatcher import route_event

__all__ = [
    'route_event',
]

