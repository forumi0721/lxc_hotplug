"""
Configuration loader supporting JSON and lightweight YAML parsing without external dependencies.
"""

import json
import os
from typing import Dict, Any


def _parse_val(val: str) -> Any:
    val = val.strip()
    if val.lower() == "true":
        return True
    elif val.lower() == "false":
        return False
    elif val.lower() in ("null", "none", "~"):
        return None
    elif (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    try:
        return int(val)
    except ValueError:
        try:
            return float(val)
        except ValueError:
            return val


def _parse_simple_yaml(text: str) -> Dict[str, Any]:
    """
    Minimalist recursive YAML parser for simple configs (key-value, nested dicts, and lists).
    Used as a fallback when PyYAML is not installed.
    """
    lines = []
    for line in text.splitlines():
        parts = line.split("#", 1)
        code = parts[0].rstrip()
        if not code or code.isspace():
            continue
        indent = len(code) - len(code.lstrip())
        lines.append((indent, code.strip()))

    def parse_block(idx: int, base_indent: int):
        if idx >= len(lines):
            return None, idx
        indent, content = lines[idx]
        if content.startswith("- "):
            result = []
            while idx < len(lines):
                cur_indent, cur_content = lines[idx]
                if cur_indent < base_indent:
                    break
                if cur_indent == base_indent and cur_content.startswith("- "):
                    item_text = cur_content[2:].strip()
                    if ":" in item_text:
                        k, v = item_text.split(":", 1)
                        k, v = k.strip(), v.strip()
                        sub_dict = {}
                        if v != "":
                            sub_dict[k] = _parse_val(v)
                        else:
                            nested_val, idx = parse_block(idx + 1, cur_indent + 2)
                            sub_dict[k] = nested_val
                            idx -= 1
                        idx += 1
                        while idx < len(lines):
                            next_indent, next_content = lines[idx]
                            if next_indent <= cur_indent or next_content.startswith("- "):
                                break
                            if ":" in next_content:
                                nk, nv = next_content.split(":", 1)
                                sub_dict[nk.strip()] = _parse_val(nv.strip())
                            idx += 1
                        result.append(sub_dict)
                    else:
                        result.append(_parse_val(item_text))
                        idx += 1
                else:
                    break
            return result, idx
        else:
            result = {}
            while idx < len(lines):
                cur_indent, cur_content = lines[idx]
                if cur_indent < base_indent:
                    break
                if cur_indent == base_indent:
                    if ":" in cur_content:
                        k, v = cur_content.split(":", 1)
                        k, v = k.strip(), v.strip()
                        if v != "":
                            result[k] = _parse_val(v)
                            idx += 1
                        else:
                            if idx + 1 < len(lines):
                                next_indent = lines[idx + 1][0]
                                child_val, next_idx = parse_block(idx + 1, next_indent)
                                result[k] = child_val
                                idx = next_idx
                            else:
                                result[k] = None
                                idx += 1
                    else:
                        idx += 1
                else:
                    break
            return result, idx

    res, _ = parse_block(0, 0)
    return res if isinstance(res, dict) else {}


def load_config(file_path: str) -> Dict[str, Any]:
    """Loads configuration from YAML or JSON file."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Config file not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Try PyYAML if installed
    try:
        import yaml
        return yaml.safe_load(content) or {}
    except ImportError:
        pass

    # Try JSON
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Fallback to simple YAML parser
    try:
        return _parse_simple_yaml(content)
    except Exception as e:
        raise ValueError(f"Failed to parse config file {file_path}: {e}")
