"""Regression tests for the pure parsing helpers in check_skill_consistency.py.

Run: python3 tools/test_check_skill_consistency.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "check_skill_consistency.py"

spec = importlib.util.spec_from_file_location("check_skill_consistency", SCRIPT)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

_numbers_near_filename = mod._numbers_near_filename
data_rows = mod.data_rows
ROW_CLAIM_RE = mod.ROW_CLAIM_RE
SCOPE_WORDS = mod.SCOPE_WORDS
COUNT_RE = mod.COUNT_RE


def case_numbers_near_filename_basic():
    line = "The file `config.yaml` (42 lines) has content."
    result = _numbers_near_filename(line)
    assert len(result) == 1
    assert result[0] == ("", "config.yaml", "42")


def case_numbers_near_filename_scoped_exempt():
    line = "On posix, `config.yaml` (42 lines) differs."
    result = _numbers_near_filename(line)
    assert result == []


def case_numbers_near_filename_two_files():
    line = "Both `a.py` (10 lines) and `b.py` (20 lines) exist."
    result = _numbers_near_filename(line)
    assert len(result) == 2
    assert result[0][1] == "a.py" and result[0][2] == "10"
    assert result[1][1] == "b.py" and result[1][2] == "20"


def case_numbers_near_filename_no_count():
    line = "See `config.yaml` for details."
    result = _numbers_near_filename(line)
    assert result == []


def case_numbers_near_filename_window_bound():
    # A count after a second filename belongs to that file, not the first
    line = "`a.py` has 100 lines `b.py` (5 lines) total."
    result = _numbers_near_filename(line)
    # a.py should not pick up the count belonging to b.py
    a_results = [r for r in result if r[1] == "a.py"]
    # The count 100 is before b.py, so it might still attach to a.py
    # but 5 should attach to b.py
    b_results = [r for r in result if r[1] == "b.py"]
    assert any(r[2] == "5" for r in b_results)


def case_numbers_near_filename_dir_key():
    line = "`scripts/run.py` (30 lines) is the entry point."
    result = _numbers_near_filename(line)
    assert len(result) == 1
    assert result[0][0] == "scripts"  # dir key
    assert result[0][1] == "run.py"


def case_numbers_near_filename_bare_basename():
    # Bare basenames match only each other
    line = "`config.yaml` (5 lines)"
    result = _numbers_near_filename(line)
    assert len(result) == 1
    assert result[0][0] == ""  # bare = empty dir key


def case_data_rows_simple():
    text = "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n"
    assert data_rows(text) == 2


def case_data_rows_no_table():
    assert data_rows("no table here") is None


def case_data_rows_header_only():
    text = "| a | b |\n|---|---|\n"
    assert data_rows(text) == 0


def case_data_rows_single_row():
    text = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    assert data_rows(text) == 1


def case_row_claim_re_basic():
    m = ROW_CLAIM_RE.search("`references/map.md` - 69 rows")
    assert m is not None
    assert m.group("path") == "references/map.md"
    assert m.group("n") == "69"


def case_row_claim_re_no_match():
    m = ROW_CLAIM_RE.search("no row claim here")
    assert m is None


def case_scope_words_not_empty():
    assert len(SCOPE_WORDS) > 0
    assert "posix" in SCOPE_WORDS


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
