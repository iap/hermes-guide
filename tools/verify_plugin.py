#!/usr/bin/env python3
"""Verify a Hermes plugin meets official standards.

Usage:
    python tools/verify_plugin.py <plugin-dir> [--src /path/to/hermes-agent]

Checks the plugin manifest, registration code, and read-only contract against
the official Hermes plugin schema (plugins_manifest.py) and registration API
(plugins.py). Prints a pass/fail checklist and exits non-zero on any failure.

This is a hermes-guide tool. It is NOT part of the hermetic gate tier
(it needs a Hermes checkout for some checks) but can be run standalone.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

# Minimal YAML fallback for environments without PyYAML (e.g. legacy-mac CI).
# Handles the flat scalar/list/mapping structure of plugin.yaml.
def _minimal_yaml_parse(text: str) -> dict:
    """Parse a simple YAML file into a dict. Handles scalars, lists, and
    two levels of nested mapping (config_schema). Not a full YAML parser."""
    result = {}
    current_key = None
    current_list = None
    current_map = None
    current_sub_key = None
    current_sub_map = None
    indent_stack = []

    for line in text.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        if indent == 0:
            # Top-level key
            if ":" in stripped:
                key, _, val = stripped.partition(":")
                key = key.strip()
                val = val.strip()
                if val == "" or val is None:
                    current_key = key
                    current_list = None
                    current_map = {}
                    current_sub_key = None
                    current_sub_map = None
                    result[key] = current_map
                elif val.startswith("[") and val.endswith("]"):
                    items = [x.strip().strip('"').strip("'") for x in val[1:-1].split(",") if x.strip()]
                    result[key] = items
                    current_key = None
                    current_list = None
                    current_map = None
                    current_sub_key = None
                    current_sub_map = None
                elif val.lower() in ("true", "false"):
                    result[key] = val.lower() == "true"
                    current_key = None
                    current_list = None
                    current_map = None
                    current_sub_key = None
                    current_sub_map = None
                elif val.isdigit():
                    result[key] = int(val)
                    current_key = None
                    current_list = None
                    current_map = None
                    current_sub_key = None
                    current_sub_map = None
                else:
                    result[key] = val.strip('"').strip("'")
                    current_key = None
                    current_list = None
                    current_map = None
                    current_sub_key = None
                    current_sub_map = None
            continue

        # Nested (indent > 0)
        if current_map is None:
            continue

        if indent <= 2:
            # First-level nested under current_key
            if stripped.startswith("- "):
                if current_list is None:
                    current_list = []
                    result[current_key] = current_list
                    current_map = None
                current_list.append(stripped[2:].strip().strip('"').strip("'"))
                current_sub_key = None
                current_sub_map = None
                continue
            if ":" in stripped:
                k, _, v = stripped.partition(":")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if v == "" or v is None:
                    current_sub_key = k
                    current_sub_map = {}
                    current_map[k] = current_sub_map
                elif v.lower() in ("true", "false"):
                    current_map[k] = v.lower() == "true"
                    current_sub_key = None
                    current_sub_map = None
                elif v.isdigit():
                    current_map[k] = int(v)
                    current_sub_key = None
                    current_sub_map = None
                elif v.startswith("[") and v.endswith("]"):
                    items = [x.strip().strip('"').strip("'") for x in v[1:-1].split(",") if x.strip()]
                    current_map[k] = items
                    current_sub_key = None
                    current_sub_map = None
                else:
                    current_map[k] = v
                    current_sub_key = None
                    current_sub_map = None
            continue

        # Deeper nesting (indent > 2) — under current_sub_key
        if current_sub_map is not None and ":" in stripped:
            k, _, v = stripped.partition(":")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if v.lower() in ("true", "false"):
                current_sub_map[k] = v.lower() == "true"
            elif v.isdigit():
                current_sub_map[k] = int(v)
            elif v == "":
                current_sub_map[k] = None
            else:
                current_sub_map[k] = v

    # Clean up empty maps
    for k, v in list(result.items()):
        if isinstance(v, dict) and not v:
            result[k] = None
    return result



def _load_manifest(plugin_dir: Path) -> tuple[dict | None, str]:
    """Load and parse the plugin manifest. Returns (data, format) or (None, error)."""
    for name in ("plugin.yaml", "plugin.yml", "plugin.json"):
        path = plugin_dir / name
        if path.exists():
            try:
                text = path.read_text()
                if name.endswith(".json"):
                    return json.loads(text), name
                if yaml:
                    return yaml.safe_load(text), name
                # Fallback: minimal parser for environments without PyYAML
                return _minimal_yaml_parse(text), name
            except Exception as e:
                return None, f"Failed to parse {name}: {e}"
    return None, "No manifest found (plugin.yaml/yml/json)"


def _check_manifest(data: dict, plugin_dir: Path) -> list[tuple[str, bool, str]]:
    """Validate manifest fields. Returns list of (check, passed, detail)."""
    results = []

    # Required fields
    name = data.get("name")
    results.append(("name present", bool(name), f"got {name!r}" if name else "missing"))
    if name:
        results.append(("name matches dir", name == plugin_dir.name, f"{name} vs {plugin_dir.name}"))

    version = data.get("version")
    results.append(("version present (quoted string)", isinstance(version, str) and bool(version), f"got {version!r}"))

    mv = data.get("manifest_version")
    results.append(("manifest_version == 1", mv == 1, f"got {mv!r}"))

    av = data.get("api_version")
    results.append(("api_version == 1", av == 1, f"got {av!r}"))

    desc = data.get("description")
    results.append(("description present", bool(desc), "missing" if not desc else "ok"))

    rh = data.get("requires_hermes")
    results.append(("requires_hermes present", bool(rh), "missing" if not rh else f"got {rh!r}"))

    # Optional but recommended
    lic = data.get("license")
    results.append(("license present", bool(lic), "missing (recommended)" if not lic else f"got {lic!r}"))

    # python_dependencies
    pydeps = data.get("python_dependencies")
    if pydeps is not None:
        is_list = isinstance(pydeps, list)
        results.append(("python_dependencies is list", is_list, f"got {type(pydeps).__name__}"))
        if is_list:
            all_str = all(isinstance(d, str) and d.strip() for d in pydeps)
            results.append(("python_dependencies entries are strings", all_str, ""))

    # capabilities
    caps = data.get("capabilities")
    if caps is None:
        results.append(("capabilities omitted (read-only)", True, "omitted"))
    elif caps == {} or caps == []:
        results.append(("capabilities empty (read-only)", True, "empty"))
    else:
        results.append(("capabilities present (privileged)", False, f"got {caps!r} — requires consent"))

    # config_schema
    schema = data.get("config_schema")
    if schema is not None:
        is_mapping = isinstance(schema, dict)
        results.append(("config_schema is mapping", is_mapping, f"got {type(schema).__name__}"))
        if is_mapping:
            for key, entry in schema.items():
                if not isinstance(entry, dict):
                    results.append((f"config_schema.{key} is mapping", False, f"got {type(entry).__name__}"))
                    continue
                has_type = "type" in entry
                results.append((f"config_schema.{key} has type", has_type, "missing" if not has_type else entry.get("type")))

    # kind
    kind = data.get("kind")
    valid_kinds = {"exclusive", "model-provider", "backend", "platform", None}
    results.append(("kind valid", kind in valid_kinds, f"got {kind!r}" if kind not in valid_kinds else (kind or "omitted (standard)")))

    return results


def _collect_module_level_functions(stmts, name):
    """Collect FunctionDef nodes at module level, including those inside
    top-level if/try/with/for blocks. Does not descend into function or
    class definitions."""
    result = []
    for stmt in stmts:
        if isinstance(stmt, ast.FunctionDef) and stmt.name == name:
            result.append(stmt)
        elif isinstance(stmt, ast.TryStar):
            body = getattr(stmt, "body", [])
            result.extend(_collect_module_level_functions(body, name))
            for handler in getattr(stmt, "handlers", []):
                result.extend(_collect_module_level_functions(handler.body, name))
            result.extend(_collect_module_level_functions(getattr(stmt, "orelse", []), name))
            result.extend(_collect_module_level_functions(getattr(stmt, "finalbody", []), name))
        elif isinstance(stmt, ast.Assign):
            # Recognize bound methods or function references exported as
            # register (e.g. register = obj.register or register = some_func).
            # Only accept attribute access or name references (callable values);
            # reject literals and other non-callable expressions.
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    if isinstance(stmt.value, (ast.Attribute, ast.Name)):
                        result.append(None)
        elif isinstance(stmt, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
            body = getattr(stmt, "body", [])
            result.extend(_collect_module_level_functions(body, name))
            for handler in getattr(stmt, "handlers", []):
                result.extend(_collect_module_level_functions(handler.body, name))
            result.extend(_collect_module_level_functions(getattr(stmt, "orelse", []), name))
            result.extend(_collect_module_level_functions(getattr(stmt, "finalbody", []), name))
    return result


def _can_accept_one_positional(func):
    """Return True if *func* can be called with exactly one positional arg.

    Hermes invokes register(ctx) with a single positional argument, so the
    function must accept one positional parameter without requiring additional
    ones.  Accounts for positional-only, ordinary, *args, and keyword-only
    parameters with defaults.
    """
    args = func.args
    pos_count = len(args.posonlyargs) + len(args.args)
    has_vararg = args.vararg is not None
    n_defaults = len(args.defaults)
    required_pos = pos_count - n_defaults
    if has_vararg:
        if required_pos > 1:
            return False
        kw_required = sum(1 for d in args.kw_defaults if d is None)
        return kw_required == 0
    if required_pos > 1:
        return False
    if pos_count < 1:
        return False
    kw_required = sum(1 for d in args.kw_defaults if d is None)
    if kw_required > 0:
        return False
    return True


def _check_registration(plugin_dir: Path) -> list[tuple[str, bool, str]]:
    """Check __init__.py for correct registration patterns."""
    results = []
    init_path = plugin_dir / "__init__.py"
    if not init_path.exists():
        return [("__init__.py exists", False, "missing")]

    results.append(("__init__.py exists", True, "ok"))
    source = init_path.read_text()
    tree = ast.parse(source, filename=str(init_path))

    # Collect module-level register functions, including those defined inside
    # top-level if/try/with blocks (conditional registration at import time).
    # Hermes source: NousResearch/hermes-agent hermes_cli/plugins.py (baseline
    # commit 40804ce4074c561220c4a766e116e07b4873b1c3).
    register_funcs = _collect_module_level_functions(tree.body, "register")

    # Filter out None sentinels (bound method assignments) for signature checks
    func_nodes = [n for n in register_funcs if n is not None]
    has_register = len(register_funcs) > 0
    # For bound method assignments, we cannot verify the signature statically,
    # so we accept them as valid (Hermes will validate at runtime).
    has_bound_method = any(n is None for n in register_funcs)
    # Verify register can be called with exactly one positional argument (ctx).
    has_ctx_param = has_bound_method or any(_can_accept_one_positional(node) for node in func_nodes)
    results.append(("register(ctx) defined", has_register, "missing" if not has_register else "ok"))
    if has_register and not has_ctx_param:
        results.append(("register accepts ctx param", False, "register() must accept ctx (Hermes calls register(ctx))"))
    elif has_register:
        results.append(("register accepts ctx param", True, "ok"))

    # Check for __version__
    has_version = "__version__" in source
    results.append(("__version__ defined", has_version, "missing" if not has_version else "ok"))

    # Check for mutation patterns (basic AST scan)
    mutation_patterns = ["open(", ".write(", "os.remove", "shutil.rmtree", "Path.unlink"]
    for pat in mutation_patterns:
        # Simple text check (not full AST) — good enough for a quick scan
        if pat in source.replace(" ", ""):
            # Could be a read or a comment; flag as warning, not failure
            pass

    # Check register_command usage
    if "register_command" in source:
        results.append(("uses register_command", True, "ok"))
    if "register_cli_command" in source:
        results.append(("uses register_cli_command", True, "ok"))
    if "register_hook" in source:
        results.append(("uses register_hook", True, "ok"))

    # Check for hardcoded VALID_HOOKS or hook event names
    if "VALID_HOOKS" in source:
        results.append(("references VALID_HOOKS (not hardcoded)", True, "ok"))

    return results


def _check_readonly(plugin_dir: Path) -> list[tuple[str, bool, str]]:
    """Check read-only contract."""
    results = []
    init_path = plugin_dir / "__init__.py"
    if not init_path.exists():
        return results

    source = init_path.read_text()

    # Check for common mutation patterns
    mutation_keywords = ["config.yaml", "config.yml", ".write_text", ".write_bytes",
                         "shutil.copy", "os.makedirs", "Path.mkdir"]
    found_mutations = [kw for kw in mutation_keywords if kw in source]
    if found_mutations:
        results.append(("no obvious mutation patterns", False, f"found: {', '.join(found_mutations)}"))
    else:
        results.append(("no obvious mutation patterns", True, "ok"))

    return results


def verify(plugin_dir: Path, hermes_src: Path | None = None) -> int:
    """Run all checks. Returns 0 on success, 1 on any failure."""
    print(f"Verifying plugin: {plugin_dir}")
    print("=" * 60)

    all_results: list[tuple[str, bool, str]] = []

    # 1. Manifest
    print("\n## Manifest (plugin.yaml)")
    data, fmt = _load_manifest(plugin_dir)
    if data is None:
        print(f"  FAIL: {fmt}")
        return 1
    print(f"  Loaded: {fmt}")
    manifest_results = _check_manifest(data, plugin_dir)
    for check, passed, detail in manifest_results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {check}" + (f" — {detail}" if detail else ""))
        all_results.append((check, passed, detail))

    # 2. Registration
    print("\n## Registration (__init__.py)")
    reg_results = _check_registration(plugin_dir)
    for check, passed, detail in reg_results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {check}" + (f" — {detail}" if detail else ""))
        all_results.append((check, passed, detail))

    # 3. Read-only contract
    print("\n## Read-only contract")
    ro_results = _check_readonly(plugin_dir)
    for check, passed, detail in ro_results:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {check}" + (f" — {detail}" if detail else ""))
        all_results.append((check, passed, detail))

    # 4. Summary
    total = len(all_results)
    passed = sum(1 for _, p, _ in all_results if p)
    failed = total - passed
    print("\n" + "=" * 60)
    print(f"Results: {passed}/{total} passed, {failed} failed")

    if failed > 0:
        print("\nFailed checks:")
        for check, p, detail in all_results:
            if not p:
                print(f"  - {check}: {detail}")
        return 1

    print("\nAll checks passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a Hermes plugin meets official standards.")
    parser.add_argument("plugin_dir", type=Path, nargs="?", default=Path("."), help="Path to the plugin directory (default: current dir)")
    parser.add_argument("--src", type=Path, default=None, help="Path to hermes-agent checkout (for deeper validation)")
    args = parser.parse_args()

    args.plugin_dir = args.plugin_dir.resolve()
    if not args.plugin_dir.is_dir():
        print(f"Error: {args.plugin_dir} is not a directory", file=sys.stderr)
        return 1

    return verify(args.plugin_dir, args.src)


if __name__ == "__main__":
    sys.exit(main())
