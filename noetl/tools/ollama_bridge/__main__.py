"""Run the Ollama bridge as ``python -m noetl.tools.ollama_bridge``."""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    host = os.environ.get("OLLAMA_BRIDGE_HOST", "0.0.0.0")
    port = int(os.environ.get("OLLAMA_BRIDGE_PORT", "8765"))
    uvicorn.run(
        "noetl.tools.ollama_bridge.server:build_app",
        host=host,
        port=port,
        factory=True,
    )


if __name__ == "__main__":
    main()
