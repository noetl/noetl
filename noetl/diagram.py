import yaml
import os
import requests
from typing import Dict, List, Tuple, Optional, Any, Set


def _sanitize_label(text: str) -> str:
    if text is None:
        return ""
    s = str(text).replace("\n", " ")
    s = s.replace("[", "(").replace("]", ")")
    s = s.replace("{", "(").replace("}", ")")
    return s


def _collect_nodes(workflow: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    nodes = {}
    for step in workflow:
        name = step.get("step")
        if not name:
            continue
        stype = "standard"
        if "loop" in step:
            stype = "loop"
        elif "end_loop" in step:
            stype = "end_loop"
        elif step.get("type"):
            stype = step.get("type")
        nodes[name] = {
            "type": stype,
            "desc": step.get("desc", ""),
            "raw": step,
        }
    return nodes


def _collect_edges(workflow: List[Dict[str, Any]]) -> List[Tuple[str, str, str]]:
    edges: List[Tuple[str, str, str]] = []
    for step in workflow:
        sname = step.get("step")
        if not sname:
            continue
        next_steps = step.get("next", [])
        if next_steps is None:
            next_steps = []
        if not isinstance(next_steps, list):
            next_steps = [next_steps]

        for nxt in next_steps:
            if isinstance(nxt, str):
                if nxt:
                    edges.append((sname, nxt, ""))
            elif isinstance(nxt, dict):
                if "when" in nxt and "then" in nxt:
                    cond = _sanitize_label(nxt.get("when", ""))
                    then_steps = nxt.get("then", [])
                    if not isinstance(then_steps, list):
                        then_steps = [then_steps]
                    for t in then_steps:
                        if isinstance(t, str):
                            to = t
                        elif isinstance(t, dict):
                            to = t.get("step")
                        else:
                            to = None
                        if to:
                            edges.append((sname, to, cond))
                if "else" in nxt:
                    else_steps = nxt.get("else", [])
                    if not isinstance(else_steps, list):
                        else_steps = [else_steps]
                    for e in else_steps:
                        if isinstance(e, str):
                            to = e
                        elif isinstance(e, dict):
                            to = e.get("step")
                        else:
                            to = None
                        if to:
                            edges.append((sname, to, "else"))
                if "step" in nxt and ("when" not in nxt and "else" not in nxt):
                    to = nxt.get("step")
                    if to:
                        edges.append((sname, to, ""))
    return edges


def _collect_loop_links(workflow: List[Dict[str, Any]]) -> List[Tuple[str, str, str]]:
    loop_names: Set[str] = set()
    end_loops: List[Tuple[str, str]] = []
    for step in workflow:
        name = step.get("step")
        if not name:
            continue
        if "loop" in step:
            loop_names.add(name)
        if "end_loop" in step:
            loop_ref = step.get("end_loop")
            if isinstance(loop_ref, str):
                end_loops.append((name, loop_ref))
    edges = []
    for end_step, loop_name in end_loops:
        if loop_name in loop_names:
            edges.append((loop_name, end_step, "[loop end]"))
    return edges


def render_plantuml(playbook: Dict[str, Any]) -> str:
    """
    Render PlantUML diagram for the given playbook dict.
    """
    name = playbook.get("name") or playbook.get("metadata", {}).get("name") or "playbook"
    workflow = playbook.get("workflow", []) or []
    nodes = _collect_nodes(workflow)
    edges = _collect_edges(workflow)
    edges += _collect_loop_links(workflow)

    lines: List[str] = []
    lines.append("@startuml")
    lines.append(f"title {_sanitize_label(name)} workflow DAG")
    lines.append("left to right direction")
    lines.append("skinparam defaultTextAlignment center")
    lines.append("skinparam linetype ortho")

    for n, meta in nodes.items():
        label = _sanitize_label(n)
        stype = meta.get("type", "")
        desc = _sanitize_label(meta.get("desc", ""))
        stereotype = f" <<{stype}>>" if stype else ""
        extra = f"\\n{desc}" if desc else ""
        lines.append(f"[{label}{extra}]{stereotype}")

    for frm, to, lbl in edges:
        if lbl == "[loop end]":
            lines.append(f"[{_sanitize_label(frm)}] ..> [{_sanitize_label(to)}] : loop end")
        else:
            label = f" : {_sanitize_label(lbl)}" if lbl else ""
            lines.append(f"[{_sanitize_label(frm)}] --> [{_sanitize_label(to)}]{label}")

    lines.append("@enduml")
    return "\n".join(lines)


def render_plantuml_file(playbook_file: str) -> str:
    with open(playbook_file, "r") as f:
        data = yaml.safe_load(f)
    return render_plantuml(data)


def render_image_kroki(puml_text: str, fmt: str = "svg", kroki_url: Optional[str] = None) -> bytes:
    """
    Render an image via Kroki from PlantUML text.

    Args:
        puml_text: The PlantUML diagram source.
        fmt: Output format, e.g., 'svg' or 'png'.
        kroki_url: Base URL for Kroki service. If None, uses NOETL_KROKI_URL env or https://kroki.io.

    Returns:
        The rendered diagram bytes.
    """
    base_url = kroki_url or os.environ.get("NOETL_KROKI_URL", "https://kroki.io")
    fmt_l = (fmt or "svg").lower()
    if fmt_l not in ("svg", "png"):
        raise ValueError(f"Unsupported image format: {fmt}")
    url = f"{base_url.rstrip('/')}/plantuml/{fmt_l}"
    headers = {"Content-Type": "text/plain"}
    resp = requests.post(url, data=puml_text.encode("utf-8"), headers=headers, timeout=45)
    if resp.status_code != 200:
        raise RuntimeError(f"Kroki rendering failed ({resp.status_code}): {resp.text[:200]}")
    return resp.content
