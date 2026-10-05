#!/usr/bin/env python3
"""Fail when the issue-template surface and the docs that describe it diverge.

Two defects in this repo's history were the same shape: a doc named a path
the reporter could not actually use.

* CONTRIBUTING.md told a reporter to pick ``config.yml`` as one of three
  templates. It is the chooser, not a form, so selecting it does nothing.
* CONTRIBUTING.md said a question is not a defect report, then pointed at
  the issue tracker -- while ``blank_issues_enabled: false`` meant there was
  no such route. A reader had nowhere to go.

Neither is visible to a linter that reads Markdown prose. These are
structural invariants over ``.github/ISSUE_TEMPLATE/`` and the one phrase
that promises a route, so CI refuses the regression.

Scope: files in the issue-template directory only. Deliberately *not* a
general "every filename in the docs exists" check -- the docs legitimately
name Hermes-side files (``config.yaml`` is ``~/.hermes/config.yaml``, not
this repo's ``.github/ISSUE_TEMPLATE/config.yml``), and ``hermes_constants.py``
lives upstream.

Usage:
    python tools/check_issue_templates.py
    python tools/check_issue_templates.py --selftest
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
TEMPLATES = Path(".github") / "ISSUE_TEMPLATE"
CHOOSER = "config.yml"

# A doc has promised a non-defect route if it says either of these.
_PROMISE = re.compile(r"^##\s+Questions?\b|not a defect report", re.MULTILINE | re.IGNORECASE)
# What counts as offering one: a form, or a contact link, named for questions.
_ROUTE = re.compile(r"question|discussion|ask|help", re.IGNORECASE)

# Docs allowed to describe the reporter-facing surface.
_DOCS = ("CONTRIBUTING.md", "README.md", "AGENTS.md")


def _load_yaml(path: Path) -> Any:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _mapping(path: Path) -> dict[str, Any]:
    """The file as a mapping; ``{}`` when it is empty or not one.

    ``_load_yaml(...) or {}`` reads the same but widens to ``object`` under
    mypy, which then rejects every ``.get`` on it.
    """
    data = _load_yaml(path)
    return data if isinstance(data, dict) else {}


def check_forms(templates: Path) -> list[str]:
    """Every non-chooser template declares name and description.

    GitHub builds the chooser entry from those two fields. A form missing
    either renders blank or is skipped, and the reporter never sees it.
    """
    bad: list[str] = []
    for form in sorted(templates.glob("*.yml")):
        if form.name == CHOOSER:
            continue
        data = _load_yaml(form)
        if not isinstance(data, dict):
            bad.append(f"{form.name}: not a YAML mapping")
            continue
        for field in ("name", "description"):
            value = data.get(field)
            if not isinstance(value, str) or not value.strip():
                bad.append(f"{form.name}: missing or empty {field!r} (chooser entry would be blank)")
    return bad


def check_chooser(templates: Path) -> list[str]:
    """Validate the chooser: schema, link hygiene, no duplicate routes."""
    path = templates / CHOOSER
    if not path.is_file():
        return [f"{CHOOSER}: missing -- GitHub needs it to pick the templates"]

    data = _load_yaml(path)
    if not isinstance(data, dict):
        return [f"{CHOOSER}: not a YAML mapping"]

    bad: list[str] = []
    blank = data.get("blank_issues_enabled")
    if not isinstance(blank, bool):
        bad.append(f"{CHOOSER}: blank_issues_enabled must be a bool, got {blank!r}")

    links = data.get("contact_links")
    if links is None:
        return bad + ([] if blank else [f"{CHOOSER}: blank issues disabled but no contact_links to reach"])

    if not isinstance(links, list):
        return bad + [f"{CHOOSER}: contact_links must be a list, got {type(links).__name__}"]

    seen: dict[str, int] = {}
    for i, link in enumerate(links):
        where = f"{CHOOSER}: contact_links[{i}]"
        if not isinstance(link, dict):
            bad.append(f"{where}: not a mapping")
            continue
        if set(link) != {"name", "url", "about"}:
            bad.append(f"{where}: keys must be exactly name/url/about, got {sorted(link)}")
            continue
        for field, value in link.items():
            if not isinstance(value, str) or not value.strip():
                bad.append(f"{where}: empty {field!r}")
        url = link.get("url", "")
        if not url.startswith("https://"):
            bad.append(f"{where}: url must be https, got {url!r}")
        elif "github.com" not in url:
            bad.append(f"{where}: url must be a github.com path, got {url!r}")
        seen[url] = seen.get(url, 0) + 1
    for url, n in seen.items():
        if n > 1:
            bad.append(f"{CHOOSER}: {url} offered {n} times; keep one entry per destination")
    return bad


def check_route_exists(repo: Path) -> list[str]:
    """A doc promising questions must not promise a route that is absent.

    Blank issues disabled means every report goes through a form or a contact
    link. If the docs say a question is not a defect report, one of those has
    to accept it -- otherwise the only advice on offer is unusable.
    """
    templates = repo / TEMPLATES
    promising = [
        repo / name
        for name in _DOCS
        if (repo / name).is_file() and _PROMISE.search((repo / name).read_text(encoding="utf-8"))
    ]
    if not promising:
        return []

    chooser = _mapping(templates / CHOOSER)
    links = chooser.get("contact_links") or []
    routes = [f"{l.get('name','')} {l.get('url','')} {l.get('about','')}" for l in links if isinstance(l, dict)]
    for form in sorted(templates.glob("*.yml")):
        if form.name == CHOOSER:
            continue
        data = _load_yaml(form)
        if isinstance(data, dict):
            routes.append(f"{data.get('name','')} {form.name}")

    if any(_ROUTE.search(r) for r in routes):
        return []

    where = ", ".join(d.name for d in promising)
    return [
        f"{where} tells the reader a question is not a defect report, but no form "
        f"or contact_links entry accepts one (blank_issues_enabled is {chooser.get('blank_issues_enabled')!r})"
    ]


def check(repo: Path) -> list[str]:
    templates = repo / TEMPLATES
    if not templates.is_dir():
        return [f"{TEMPLATES}: missing"]
    return (
        check_forms(templates)
        + check_chooser(templates)
        + check_route_exists(repo)
    )


def selftest() -> int:
    good_chooser = (
        "blank_issues_enabled: false\n"
        "contact_links:\n"
        "  - name: Hermes core bug\n"
        "    url: https://github.com/NousResearch/hermes-agent/issues\n"
        "    about: Upstream.\n"
    )
    # A doc that steers questions away from a defect form.
    promise = "## Questions\n\nA question is not a defect report.\n"
    cases = [
        # (templates, docs, expected failure fragments)
        # --- the #147 defect: doc promises a route, nothing offers one ---
        ({"config.yml": good_chooser}, {"CONTRIBUTING.md": promise},
         ["no form or contact_links entry accepts one"]),
        # ...and the same, with a form present but no question route.
        ({"config.yml": good_chooser, "bug-report.yml": "name: Bug\ndescription: d\n"},
         {"CONTRIBUTING.md": promise},
         ["no form or contact_links entry accepts one"]),
        # The promise only bites when a route could plausibly accept it.
        ({"config.yml": "blank_issues_enabled: false\ncontact_links:\n"
                        "  - name: Question about a skill\n"
                        "    url: https://github.com/iap/hermes-guide/discussions\n"
                        "    about: Ask here.\n",
          "bug-report.yml": "name: Bug\ndescription: d\n"},
         {"CONTRIBUTING.md": promise}, []),
        # A form named for questions satisfies it too.
        ({"config.yml": good_chooser,
          "question.yml": "name: Question\ndescription: ask away\n"},
         {"CONTRIBUTING.md": promise}, []),
        # No promise in the docs: nothing to enforce, whatever the routes.
        ({"config.yml": good_chooser}, {"CONTRIBUTING.md": "nothing here\n"}, []),
        # --- chooser schema ---
        ({"config.yml": "blank_issues_enabled: maybe\n"}, {}, ["must be a bool"]),
        ({"config.yml": "blank_issues_enabled: false\ncontact_links:\n"
                        "  - name: A\n    url: http://x.example/y\n    about: z\n"}, {},
         ["url must be https"]),
        ({"config.yml": "blank_issues_enabled: false\ncontact_links:\n"
                        "  - name: A\n    url: https://example.org/o/r\n    about: z\n"}, {},
         ["must be a github.com path"]),
        ({"config.yml": "blank_issues_enabled: false\ncontact_links:\n"
                        "  - name: A\n    url: https://github.com/o/r\n    about: z\n"
                        "  - name: B\n    url: https://github.com/o/r\n    about: z2\n"}, {},
         ["offered 2 times"]),
        ({"config.yml": "blank_issues_enabled: false\ncontact_links:\n"
                        "  - name: A\n    url: https://github.com/o/r\n"}, {},
         ["keys must be exactly"]),
        ({"config.yml": "blank_issues_enabled: false\n"}, {},
         ["no contact_links to reach"]),
        ({}, {}, ["config.yml: missing"]),
        # --- forms ---
        ({"config.yml": good_chooser, "bug-report.yml": "description: d\n"}, {},
         ["missing or empty 'name'"]),
        ({"config.yml": good_chooser, "bug-report.yml": "name: B\n"}, {},
         ["missing or empty 'description'"]),
        ({"config.yml": good_chooser,
          "bug-report.yml": "name: B\ndescription: d\n"}, {}, []),
        # --- clean by construction: blank issues allowed, so no route needed ---
        ({"config.yml": "blank_issues_enabled: true\n",
          "bug-report.yml": "name: B\ndescription: d\n"}, {"CONTRIBUTING.md": promise}, []),
    ]

    failures = 0
    for templates, docs, expect in cases:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tdir = root / TEMPLATES
            tdir.mkdir(parents=True)
            for name, body in templates.items():
                (tdir / name).write_text(body, encoding="utf-8")
            for name, body in docs.items():
                (root / name).write_text(body, encoding="utf-8")
            got = check(root)
        missing = [e for e in expect if not any(e in g for g in got)]
        if missing:
            failures += 1
            print(f"SELFTEST FAIL: expected {missing}, got {got}", file=sys.stderr)
    if failures:
        print(f"error: {failures}/{len(cases)} selftest case(s) failed", file=sys.stderr)
        return 1
    print(f"OK: selftest {len(cases)} case(s) passed")
    return 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()

    bad = check(REPO)
    if bad:
        print("FAIL: issue-template surface does not match the docs:", file=sys.stderr)
        for line in bad:
            print(f"  {line}", file=sys.stderr)
        print(
            "\nA reporter must be able to follow the docs literally. If a route\n"
            "changes, update CONTRIBUTING.md and the chooser together.",
            file=sys.stderr,
        )
        return 1

    n_forms = len([p for p in (REPO / TEMPLATES).glob("*.yml") if p.name != CHOOSER])
    n_links = len(_mapping(REPO / TEMPLATES / CHOOSER).get("contact_links") or [])
    print(f"OK: {n_forms} template(s), {n_links} contact link(s), docs agree")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))