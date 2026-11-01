"""Regression tests for the pure parsing helpers in check_cli_surface.py.

Run: python3 tools/test_check_cli_surface.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "check_cli_surface.py"

spec = importlib.util.spec_from_file_location("check_cli_surface", SCRIPT)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

_usage_names = mod._usage_names
_canonical_command = mod._canonical_command
_enum_values = mod._enum_values
_usage_flags = mod._usage_flags
_cite_parts = mod._cite_parts
_negated = mod._negated


def case_usage_names_braces():
    assert _usage_names("usage: hermes skills {install,uninstall,list}\n") == {"install", "uninstall", "list"}


def case_usage_names_four_space():
    assert _usage_names("    chat      Interactive chat\n    skills    Manage skills\n") == {"chat", "skills"}


def case_usage_names_skips_option_value_braces():
    assert "all" not in _usage_names("usage: hermes x --source {all,hub}\n")


def case_usage_names_empty():
    assert _usage_names("") == set()


def case_usage_names_alias_group():
    assert "desktop" in _usage_names("    desktop (gui)    Launch desktop\n")


def case_canonical_command_found():
    assert _canonical_command("usage: hermes skills list\n") == "skills"


def case_canonical_command_missing():
    assert _canonical_command("no usage line here") is None


def case_enum_values_braces():
    vals = _enum_values("positional arguments:\n  log_name  {agent,errors,gateway}\n")
    assert "agent" in vals and "errors" in vals and "gateway" in vals


def case_enum_values_empty():
    assert _enum_values("") == set()


def case_usage_flags_long():
    flags = _usage_flags("  --verbose  Verbose output\n  --dry-run  Dry run\n")
    assert "--verbose" in flags and "--dry-run" in flags


def case_usage_flags_short_brackets():
    assert "-v" in _usage_flags("usage: hermes x [-v] [-f FILE]\n")


def case_cite_parts_simple():
    pos, flags = _cite_parts("skills install --yes")
    assert pos == ["skills", "install"] and "--yes" in flags


def case_cite_parts_session_prefix():
    assert _cite_parts("/doctor") is None


def case_cite_parts_no_positionals():
    assert _cite_parts("--help") is None


def case_cite_parts_placeholder():
    pos, _ = _cite_parts("config set <key> <value>")
    assert pos == ["config", "set"]


def case_cite_parts_value_flag_skips_next():
    pos, flags = _cite_parts("skills install -m provider foo --yes")
    assert pos == ["skills", "install", "foo"]
    assert "--yes" in flags
    assert "provider" not in pos


def case_cite_parts_value_flag_long():
    pos, _ = _cite_parts("run --provider openai chat")
    assert pos == ["run", "chat"] and "openai" not in pos


def case_cite_parts_dotted():
    pos, _ = _cite_parts("config set key value.yaml")
    assert pos == ["config", "set", "key"]


def case_cite_parts_path():
    pos, _ = _cite_parts("import file /path/to/file")
    assert pos == ["import", "file"]


def case_cite_parts_allcaps():
    pos, _ = _cite_parts("run --for-tool TOOL_NAME")
    assert pos == ["run"]


def case_cite_parts_max_three():
    pos, _ = _cite_parts("a b c d e")
    assert len(pos) == 3


def case_negated_no_command():
    line = "There is no `hermes voice status` command."
    pos = line.index("`hermes")
    assert _negated(line, pos) is True


def case_negated_not_installed():
    line = "hermes voice is not installed. Run `hermes doctor`."
    pos = line.index("Run `hermes")
    assert _negated(line, pos) is False


def case_negated_never():
    line = "Never run `hermes db vacuum`."
    pos = line.index("`hermes")
    assert _negated(line, pos) is True


def case_negated_contrast():
    line = "not X but `hermes real cmd` works."
    pos = line.index("`hermes")
    assert _negated(line, pos) is False


def main() -> int:
    cases = [v for k, v in globals().items() if k.startswith("case_")]
    failures = []
    for case in cases:
        try:
            case()
            print(f"OK: {case.__name__}")
        except Exception as exc:
            failures.append(f"{case.__name__}: {exc}")
            print(f"FAIL: {case.__name__}: {exc}")
    if failures:
        print(f"\n{len(failures)} failure(s)")
        return 1
    print(f"\nOK: {len(cases)} case(s) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
