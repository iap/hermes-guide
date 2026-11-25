"""Pytest parametrisation of the check-envelope regression cases.

The authoritative cases live in ``tools/test_check_envelopes.py`` and are run
there directly by CI as a script. This module reuses those exact case functions
through the shared ``checks`` fixture so each one is collected and reported as
an individual pytest case, without duplicating assertions.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_TOOL = REPO_ROOT / "tools" / "test_check_envelopes.py"

_spec = importlib.util.spec_from_file_location("check_envelopes_cases", _TOOL)
assert _spec is not None and _spec.loader is not None
_cases_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cases_module)

CASES = _cases_module.CASES


@pytest.mark.parametrize("case", CASES, ids=[case.__name__ for case in CASES])
def test_envelope_case(case, checks):
    case(checks)
