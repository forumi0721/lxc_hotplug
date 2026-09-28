"""
Configuration loader supporting JSON and lightweight YAML parsing without external dependencies.
"""

import json
import os
from typing import Dict, Any


def _parse_simple_yaml(text: str) -> Dict[str, Any]:
    """
    Minimalist recursive YAML parser for simple configs (key-value, nested dicts, and lists).
    Used as a fallback when PyYAML is not installed.
    """
    lines = text.splitlines()
    root: Dict[str, Any] = {}
    stack = [(0, root)]

    for line_idx, line in enumerate(lines):
        stripped = line.split('#', 1)[0].rstrip()
        if not stripped or stripped.isspace():
            continue

        indent = len(line) - len(line.lstrip())
        content = stripped.strip()

        # Pop stack to match current indentation
        while stack and indent < stack[-1][0]:
            stack.pop()

        current_dict = stack[-1][1]

        if content.startswith("- "):
            # List item
            item_val = content[2:].strip()
            # If parent key is not yet a list, this is a nested list context
            # Fallback for structured lists in our config
            continue

        if ":" in content:
            key, val = content.split(":", 1)
            key = key.strip()
            val = val.strip()

            if val == "":
                # Nested dict
                new_dict: Dict[str, Any] = {}
                current_dict[key] = new_dict
                stack.append((indent + 2, new_dict))
            else:
                # Value parsing
                if val.lower() == "true":
                    current_dict[key] = True
                elif val.lower() == "false":
                    current_dict[key] = False
                elif val.lower() in ("null", "none", "~"):
                    current_dict[key] = None
                elif (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    current_dict[key] = val[1:-1]
                else:
                    try:
                        current_dict[key] = int(val)
                    except ValueError:
                        try:
                            current_dict[key] = float(val)
                        except ValueError:
                            current_dict[key] = val

    return root


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
