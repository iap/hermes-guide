#!/usr/bin/env python3
"""F5 regression: a portable ``plugin.json``-only plugin must be discovered.

``_read_plugin_manifest`` originally accepted only ``plugin.yaml``/``plugin.yml``,
so any enabled plugin that ships only a portable Agent Plugin ``plugin.json``
(manifest schema ``agent-plugins.org``) was reported as
"enabled but no matching plugin manifest was found" — a false positive on a
plugin Hermes itself loads and lists (e.g. pstack v0.14.8).

Hermes's own ``scan_directory`` resolves all three forms, so the check must too.

Guards:

1. A directory with only ``plugin.json`` (valid ``name``) is discovered by name.
2. A directory with only ``plugin.json`` (missing/empty ``name``) falls back to
   the directory basename — same contract as the YAML path.
3. A directory with only ``plugin.json`` (malformed JSON) returns None and is
   not reported as a plugin (matches Hermes's fail-open behaviour).
4. A directory with ``plugin.yaml`` still wins over ``plugin.json`` when both
   are present (YAML first in the resolution order).
5. A directory with neither manifest nor ``plugin.json`` returns None.

Uses a synthetic ``$HERMES_HOME`` and never invokes the ``hermes`` CLI.

Run: python3 tools/test_portable_plugin_manifest.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(argv: list[str]) -> int:
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as td:
        pkg = Path(td) / "hermes_guide"
        pkg.mkdir()
        for name in ("__init__.py", "checks.py", "constants.py"):
            shutil.copy(REPO / name, pkg / name)
        sys.path.insert(0, td)

        import hermes_guide.checks as checks  # noqa: E402

        # (1) portable plugin.json with a name -> discovered by name
        d = Path(td) / "portable"
        _write(d / "plugin.json", json.dumps({"name": "portable-plugin", "version": "1.0.0"}))
        if checks._read_plugin_manifest(str(d)) != "portable-plugin":
            failures.append("portable plugin.json name not discovered")

        # (2) portable plugin.json without a name -> basename fallback
        d2 = Path(td) / "no-name"
        _write(d2 / "plugin.json", json.dumps({"version": "1.0.0"}))
        if checks._read_plugin_manifest(str(d2)) != "no-name":
            failures.append("portable plugin.json without name did not fall back to basename")

        # (2b) portable plugin.json with empty name -> basename fallback
        d2b = Path(td) / "empty-name"
        _write(d2b / "plugin.json", json.dumps({"name": "", "version": "1.0.0"}))
        if checks._read_plugin_manifest(str(d2b)) != "empty-name":
            failures.append("portable plugin.json with empty name did not fall back to basename")

        # (2c) YAML plugin.yaml with empty name -> basename fallback
        d2c = Path(td) / "yaml-empty-name"
        _write(d2c / "plugin.yaml", "name: \"\"\nversion: 1.0.0\n")
        if checks._read_plugin_manifest(str(d2c)) != "yaml-empty-name":
            failures.append("plugin.yaml with empty name did not fall back to basename")

        # (3) malformed plugin.json -> None (not a plugin)
        d3 = Path(td) / "bad-json"
        _write(d3 / "plugin.json", "{ not json")
        if checks._read_plugin_manifest(str(d3)) is not None:
            failures.append("malformed plugin.json was treated as a plugin")

        # (3b) malformed plugin.yaml -> None (not a plugin). A corrupt YAML
        # manifest must not fall back to the basename and report a broken
        # plugin as discovered/healthy.
        d3b = Path(td) / "bad-yaml"
        _write(d3b / "plugin.yaml", "name: [unclosed\n  bad: : :\n")
        if checks._read_plugin_manifest(str(d3b)) is not None:
            failures.append("malformed plugin.yaml was treated as a plugin")

        # (3c) list-root plugin.yaml -> None (no name mapping to read)
        d3c = Path(td) / "list-yaml"
        _write(d3c / "plugin.yaml", "- just\n- a\n- list\n")
        if checks._read_plugin_manifest(str(d3c)) is not None:
            failures.append("list-root plugin.yaml was treated as a plugin")

        # (3d) a non-string name is not an identifier -> None. Feeding a list
        # into the collector's set used to crash the whole plugins check.
        d3d = Path(td) / "list-name"
        _write(d3d / "plugin.yaml", "name: [not, a, string]\n")
        if checks._read_plugin_manifest(str(d3d)) is not None:
            failures.append("plugin.yaml with a list-valued name was treated as a plugin")

        # (3e) numeric/boolean names are equally unusable.
        d3e = Path(td) / "number-name"
        _write(d3e / "plugin.yaml", "name: 123\n")
        if checks._read_plugin_manifest(str(d3e)) is not None:
            failures.append("plugin.yaml with a numeric name was treated as a plugin")

        # (3f) an empty name falls back to the directory basename.
        d3f = Path(td) / "blank-name"
        _write(d3f / "plugin.yaml", 'name: ""\n')
        if checks._read_plugin_manifest(str(d3f)) != "blank-name":
            failures.append("plugin.yaml with an empty name did not fall back to basename")

        # (3f2) padded names are preserved verbatim: Hermes gates on the raw
        # manifest name, so stripping would create a false healthy.
        d3f2 = Path(td) / "padded-name"
        _write(d3f2 / "plugin.yaml", 'name: "  padded  "\n')
        if checks._read_plugin_manifest(str(d3f2)) != "  padded  ":
            failures.append("plugin.yaml with a padded name was normalized")

        # (3g) the portable path applies the same type guard.
        d3g = Path(td) / "portable-list-name"
        _write(d3g / "plugin.json", json.dumps({"name": ["not", "a", "string"]}))
        if checks._read_plugin_manifest(str(d3g)) is not None:
            failures.append("plugin.json with a list-valued name was treated as a plugin")

        # (4) plugin.yaml wins over plugin.json when both present
        d4 = Path(td) / "both"
        _write(d4 / "plugin.yaml", "name: yaml-wins\nversion: 1.0.0\n")
        _write(d4 / "plugin.json", json.dumps({"name": "json-loses", "version": "1.0.0"}))
        if checks._read_plugin_manifest(str(d4)) != "yaml-wins":
            failures.append("plugin.yaml did not win over plugin.json")

        # (5) no manifest at all -> None
        d5 = Path(td) / "empty"
        d5.mkdir(parents=True, exist_ok=True)
        if checks._read_plugin_manifest(str(d5)) is not None:
            failures.append("manifest-less directory was treated as a plugin")

        # (6) behavioral: an enabled portable plugin is not reported missing
        home = Path(td) / "home"
        plugins = home / "plugins"
        _write(plugins / "portable-only/plugin.json",
               json.dumps({"name": "portable-only", "version": "1.0.0"}))
        config = home / "config.yaml"
        _write(config, "plugins:\n  enabled:\n    - portable-only\n  disabled: []\n")

        checks._store().clear()
        checks._hermes_config_path = lambda: str(config)
        checks._hermes_home_from_library = lambda: str(home)
        checks._bundled_plugins_dir = lambda: None

        result = checks.check_plugins()
        if result.get("status") == "broken":
            failures.append(f"enabled portable plugin wrongly reported missing: {result!r}")
        # On healthy the detail is the sorted enabled list (expected to contain
        # the name); on informational it is a list of notes. Only the notes
        # portion must not mention the enabled plugin.
        detail = result.get("detail")
        notes = []
        if isinstance(detail, list) and result.get("status") == "informational":
            notes = [str(d) for d in detail]
        elif isinstance(detail, list) and result.get("status") == "healthy":
            notes = []  # detail is the enabled list, not findings
        joined = " | ".join(notes)
        if "portable-only" in joined:
            failures.append(f"enabled portable plugin should not appear in notes: {joined}")

        # (7) a malformed name must not crash the collector. This is the F2
        # regression: `seen.add(name)` raised TypeError for a list name and
        # run_all surfaced CHECK_CRASHED instead of a plugin finding.
        _write(plugins / "bad-name" / "plugin.yaml", "name: [not, a, string]\n")
        _write(config, "plugins:\n  enabled: [bad-name]\n  disabled: []\n")
        original_upstream = checks._upstream_manifests
        checks._upstream_manifests = lambda home: None
        checks._store().clear()
        try:
            result = checks.check_plugins()
        except Exception as exc:  # noqa: BLE001 - the regression this case pins
            failures.append(f"malformed manifest name crashed check_plugins: {exc!r}")
        else:
            joined = " | ".join(str(d) for d in (result.get("detail") or []))
            if result.get("id") == "CHECK_CRASHED":
                failures.append(f"malformed manifest name reported as a crash: {result!r}")
            if result.get("status") != "broken" or "bad-name" not in joined:
                failures.append(f"malformed manifest verdict wrong: {result!r}")
        finally:
            checks._upstream_manifests = original_upstream

        # (8) padded manifest names must not be normalized into an enabled
        # match. Hermes preserves the raw name, so `enabled: [padded]` does not
        # activate a manifest named `"  padded  "`.
        _write(plugins / "padded" / "plugin.yaml", 'name: "  padded  "\n')
        _write(config, "plugins:\n  enabled: [padded]\n  disabled: []\n")
        checks._upstream_manifests = lambda home: None
        checks._store().clear()
        try:
            result = checks.check_plugins()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"padded manifest name crashed check_plugins: {exc!r}")
        else:
            joined = " | ".join(str(d) for d in (result.get("detail") or []))
            if result.get("status") != "broken" or "padded" not in joined:
                failures.append(f"padded manifest name matched a stripped id: {result!r}")
        finally:
            checks._upstream_manifests = original_upstream

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1

    print("OK: portable plugin.json plugins are discovered (F5)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))