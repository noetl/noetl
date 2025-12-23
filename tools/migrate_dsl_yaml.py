#!/usr/bin/env python3
import sys
import re
import logging
from pathlib import Path
from typing import Any, Dict

import yaml

logger = logging.getLogger(__name__)


def merge_data(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(dst or {})
    for k, v in (src or {}).items():
        if k not in out:
            out[k] = v
    return out


def transform_strings(value: Any, loop_step_name: str | None) -> Any:
    if isinstance(value, str):
        s = value
        # outputs.<step>.* -> <step>.result.*
        s = re.sub(r"\{\{\s*outputs\.([A-Za-z0-9_]+)", r"{{ \1.result", s)
        # output... -> result...
        s = re.sub(r"\{\{\s*output\b", r"{{ result", s)
        # loop index heuristic
        if loop_step_name:
            s = s.replace("_loop.current_index", f"{loop_step_name}.result_index")
        return s
    return value


def transform_node(node: Any, current_step_name: str | None = None, current_step_type: str | None = None, loop_step_name: str | None = None) -> Any:
    if isinstance(node, dict):
        # Step name/type detection for iterator context
        step_name = node.get('step') or node.get('name') or current_step_name
        step_type = node.get('type') or current_step_type

        out: Dict[str, Any] = {}

        # Key renames and structural transforms first
        # 1) loop -> iterator conversion
        if 'loop' in node and isinstance(node['loop'], dict):
            lp = node['loop']
            node = dict(node)
            node.pop('loop', None)
            node.setdefault('type', 'iterator')
            if 'in' in lp and 'data' not in node:
                node['data'] = lp.get('in')
            if 'iterator' in lp and 'element' not in node:
                node['element'] = lp.get('iterator')
            if 'task' in lp and 'task' not in node:
                node['task'] = lp.get('task')
            if 'save' in lp and 'save' not in node:
                node['save'] = lp.get('save')

        # 2) collection/iterator -> data/element for iterator type
        if str(node.get('type') or '').lower() == 'iterator':
            if 'collection' in node and 'data' not in node:
                node['data'] = node.pop('collection')
            if 'iterator' in node and 'element' not in node:
                node['element'] = node.pop('iterator')

        # 3) Generic key renames: with -> data, params -> data
        # Merge into existing data; data wins on conflicts
        merged = {}
        for alias in ('with', 'params', 'args'):
            if alias in node and isinstance(node[alias], dict):
                merged.update(node[alias])
        if 'data' in node and isinstance(node['data'], dict):
            merged.update(node['data'])
        if merged:
            out['data'] = merged

        # Copy through other keys, skipping aliases moved above
        for k, v in node.items():
            if k in ('with', 'params', 'args'):
                continue
            if k == 'collection' and str(node.get('type') or '').lower() == 'iterator':
                continue
            if k == 'iterator' and str(node.get('type') or '').lower() == 'iterator':
                continue
            out[k] = v

        # 4) Transform next[] payload blocks: with/input/payload -> data
        nxt = out.get('next')
        if isinstance(nxt, list):
            nn = []
            for it in nxt:
                if isinstance(it, dict):
                    it2 = dict(it)
                    carry = {}
                    for alias in ('with', 'input', 'payload'):
                        if alias in it2 and isinstance(it2[alias], dict):
                            carry.update(it2[alias])
                            it2.pop(alias, None)
                    if carry:
                        if 'data' in it2 and isinstance(it2['data'], dict):
                            d = dict(carry)
                            d.update(it2['data'])
                            it2['data'] = d
                        else:
                            it2['data'] = carry
                    nn.append(it2)
                else:
                    nn.append(it)
            out['next'] = nn

        # 5) Recurse and string transforms
        # Determine iterator step name to rewrite _loop.current_index
        iter_step_name = loop_step_name
        if str(out.get('type') or '').lower() == 'iterator' and step_name:
            iter_step_name = str(step_name)

        new_out: Dict[str, Any] = {}
        for k, v in out.items():
            if isinstance(v, (dict, list)):
                # If nested under "task" of an iterator step, set loop_step_name
                child_loop = iter_step_name if (k == 'task' and iter_step_name) else loop_step_name
                new_out[k] = transform_node(v, step_name, out.get('type') or step_type, child_loop)
            else:
                new_out[k] = transform_strings(v, iter_step_name)

        return new_out

    if isinstance(node, list):
        return [transform_node(x, current_step_name, current_step_type, loop_step_name) for x in node]

    # Scalars
    return transform_strings(node, loop_step_name)


def process_file(path: Path) -> bool:
    text = path.read_text(encoding='utf-8')
    try:
        data = yaml.safe_load(text)
    except Exception:
        # Fallback: regex-only replacements when YAML parsing fails
        new_text = re.sub(r"(^|\s)with:\s", r" data: ", text)
        new_text = re.sub(r"(^|\s)params:\s", r" data: ", new_text)
        # next: ... input: -> data:
        new_text = re.sub(r"(\n\s*next:\n(?s:.*?)\n\s*)(input:)\s*", r"\1data:", new_text)
        new_text = re.sub(r"\{\{\s*outputs\.([A-Za-z0-9_]+)", r"{{ \1.result", new_text)
        new_text = re.sub(r"\{\{\s*output\b", r"{{ result", new_text)
        if new_text != text:
            path.write_text(new_text, encoding='utf-8')
            return True
        return False

    if data is None:
        return False

    new_data = transform_node(data)
    if new_data == data:
        return False
    path.write_text(yaml.safe_dump(new_data, sort_keys=False), encoding='utf-8')
    return True


def main() -> int:
    changed = 0
    for p in Path('.').rglob('*'):
        if p.suffix.lower() in {'.yaml', '.yml'} and p.is_file():
            if 'node_modules' in p.parts or '.venv' in p.parts or '.github' in p.parts:
                continue
            try:
                if process_file(p):
                    logger.info(f"migrated: {p}")
                    changed += 1
            except Exception as e:
                logger.info(f"WARN: failed migrating {p}: {e}")
    logger.info(f"Total migrated files: {changed}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
