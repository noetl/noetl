"""
Playbook action executor package for NoETL.

This package handles 'playbook' type tasks which execute sub-playbooks
via the broker orchestration engine.

Package Structure:
    - loader.py: Playbook content loading from path or inline content
    - context.py: Context building and parent tracking
    - executor.py: Main playbook task execution orchestrator
"""

from .executor import execute_playbook_task

__all__ = ['execute_playbook_task']
