"""Pytest parametrisation of the finding-id contract cases.

The authoritative cases live in ``tools/test_finding_ids.py`` and are run
there directly by CI. This module reuses those exact case functions through
the shared ``checks`` fixture so each is reported as an individual pytest case,
without duplicating assertions.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_TOOL = REPO_ROOT / "tools" / "test_finding_ids.py"

_spec = importlib.util.spec_from_file_location("finding_ids_cases", _TOOL)
assert _spec is not None and _spec.loader is not None
_cases_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cases_module)

CASES = _cases_module.CASES


@pytest.mark.parametrize("case", CASES, ids=[case.__name__ for case in CASES])
def test_finding_id_case(case, checks):
    case(checks)
