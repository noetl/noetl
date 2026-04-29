"""Shell plugin package for NoETL.

Lets ``kind: shell`` steps run inside the distributed worker (NATS
dispatcher → worker pod), not just under the local rust binary.
The lifecycle agents in ``automation/agents/kubernetes/`` and similar
were stranded by this gap — they could be invoked from
``noetl run --runtime local`` but failed at the worker with
``NotImplementedError("Tool kind 'shell' not implemented")`` whenever
the noetl server's MCP / catalog dispatcher routed them through NATS.
"""

from noetl.tools.shell.executor import execute_shell_task

__all__ = ["execute_shell_task"]
