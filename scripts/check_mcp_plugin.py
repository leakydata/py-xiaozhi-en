#!/usr/bin/env python3
"""Check the structure of an external MCP plugin package, without starting the whole app."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def check_plugin(path: Path, *, strict: bool = False) -> list[str]:
    """Return the list of problems; an empty list means it passed."""
    errors: list[str] = []
    if not path.is_dir():
        return [f"not a directory: {path}"]

    manifest_path = path / "manifest.json"
    plugin_py = path / "plugin.py"
    if not manifest_path.is_file() and not plugin_py.is_file():
        errors.append("there is no manifest.json and no plugin.py")
        return errors

    manifest: dict = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append(f"manifest.json could not be parsed: {e}")
            return errors
    else:
        if strict:
            errors.append("strict mode requires a manifest.json")
        manifest = {"id": path.name, "entry": "plugin:register"}

    pid = manifest.get("id") or path.name
    if not pid:
        errors.append("manifest.id is empty")

    entry = str(manifest.get("entry") or "plugin:register")
    if ":" not in entry:
        errors.append(f"entry must be module:attr, got: {entry}")
    else:
        mod, _attr = entry.split(":", 1)
        py = path / f"{mod.replace('.', '/')}.py"
        if not py.is_file() and not (path / mod).is_dir():
            errors.append(f"the entry module file is missing: {py}")

    runtime = manifest.get("runtime", "python-inprocess")
    if runtime != "python-inprocess":
        errors.append(
            f"only runtime=python-inprocess is supported at the moment, got: {runtime}"
        )

    if strict:
        if "api_version" not in manifest:
            errors.append("strict mode requires api_version")
        if "python_abi" not in manifest:
            errors.append("strict mode requires python_abi")
        if "platforms" not in manifest:
            errors.append("strict mode requires platforms")
        if "tool_name_prefix" not in manifest:
            errors.append("strict mode requires tool_name_prefix")

    # lib is optional, but if it is there it has to be a directory
    lib = path / "lib"
    if lib.exists() and not lib.is_dir():
        errors.append("lib exists but is not a directory")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check an external MCP plugin package: its manifest, its entry point, and its optional lib directory"
    )
    parser.add_argument(
        "path",
        type=Path,
        help="path to the plugin directory, e.g. mcp_plugins/com.example.hello",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="also require api_version, python_abi, platforms and tool_name_prefix",
    )
    args = parser.parse_args(argv)
    path = args.path.expanduser().resolve()
    errs = check_plugin(path, strict=args.strict)
    if errs:
        print(f"FAIL {path}")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(f"OK {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
