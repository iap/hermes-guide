"""Regression tests for pure helpers in check_upstream_drift.py.

Run: python3 tools/test_upstream_drift.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "check_upstream_drift.py"

spec = importlib.util.spec_from_file_location("check_upstream_drift", SCRIPT)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

_tag_key = mod._tag_key
_cap_chars = mod._cap_chars
_fit_body = mod._fit_body
_uncapped = mod._uncapped
MAX_BODY_CHARS = mod.MAX_BODY_CHARS


def case_tag_key_basic():
    assert _tag_key("v2026.8.16") == (2026, 8, 16)


def case_tag_key_with_patch():
    assert _tag_key("v2026.8.16.2") == (2026, 8, 16, 2)


def case_tag_key_ordering():
    assert _tag_key("v2026.8.16") < _tag_key("v2026.8.17")
    assert _tag_key("v2026.8.16") < _tag_key("v2026.9.1")
    assert _tag_key("v2026.8.16.1") < _tag_key("v2026.8.16.2")


def case_tag_key_v_prefix():
    assert _tag_key("v1.2.3") == (1, 2, 3)


def case_tag_key_non_digit():
    assert _tag_key("v1.2.abc") == (1, 2, 0)


def case_cap_chars_under_limit():
    entries = ["short entry", "another entry"]
    result = _cap_chars(entries, 1000, "omitted {omitted}")
    assert result == "short entry\nanother entry"


def case_cap_chars_over_limit():
    entries = ["a" * 50, "b" * 50, "c" * 50]
    result = _cap_chars(entries, 60, "omitted {omitted}")
    # Should keep first entry and note about omitted
    assert "a" * 50 in result
    assert "omitted" in result


def case_cap_chars_empty():
    result = _cap_chars([], 1000, "omitted {omitted}")
    assert result == ""


def case_cap_chars_single_entry():
    result = _cap_chars(["hello"], 1000, "omitted {omitted}")
    assert result == "hello"


def case_fit_body_basic():
    sections = "a" * 100
    footer = "footer text"
    result = _fit_body(sections, footer)
    assert footer in result
    assert len(result) <= MAX_BODY_CHARS


def case_fit_body_footer_preserved():
    sections = "x" * (MAX_BODY_CHARS + 100)
    footer = "IMPORTANT FOOTER"
    result = _fit_body(sections, footer)
    assert "IMPORTANT FOOTER" in result


def case_fit_body_truncation_note():
    sections = "x" * (MAX_BODY_CHARS + 100)
    footer = "footer"
    result = _fit_body(sections, footer)
    assert "truncated" in result.lower() or "Body truncated" in result


def case_uncapped_default_false():
    # Default (no env vars) should be False
    os.environ.pop("DRIFT_NO_CAP", None)
    os.environ.pop("DRIFT_DRY_RUN", None)
    assert _uncapped() is False


def case_uncapped_requires_both():
    os.environ["DRIFT_NO_CAP"] = "1"
    os.environ.pop("DRIFT_DRY_RUN", None)
    assert _uncapped() is False
    os.environ["DRIFT_DRY_RUN"] = "1"
    assert _uncapped() is True
    # cleanup
    os.environ.pop("DRIFT_NO_CAP", None)
    os.environ.pop("DRIFT_DRY_RUN", None)


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
