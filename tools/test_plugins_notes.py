#!/usr/bin/env python3
"""F2 regression: only real plugins may be reported as "not enabled".

The notes loop in ``check_plugins`` tested nothing but ``os.path.isdir``, while
``_collect_plugin_ids`` requires a ``plugin.yaml``/``plugin.yml`` manifest. Any
stray directory under ``$HERMES_HOME/plugins`` was therefore announced as an
opt-in plugin — on the reference install that meant a state-file directory and
a vendored Node checkout were reported on every run.

Guards:

1. A manifest-less directory produces no note (core does not treat it as a
   plugin either).
2. A directory with a manifest, not listed in enabled/disabled, still produces
   a note (the real feature keeps working).
3. The note is keyed on the manifest ``name``, not the directory basename, so a
   plugin whose manifest name differs from its directory is reported once and
   under the identifier ``plugins.enabled`` actually matches.
4. An enabled plugin whose manifest name differs from its directory is not
   reported as missing.

Uses a synthetic ``$HERMES_HOME`` and never invokes the ``hermes`` CLI.

Run: python3 tools/test_plugins_notes.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

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

        home = Path(td) / "home"
        plugins = home / "plugins"

        # stray dirs with NO manifest — must never be reported
        _write(plugins / "state-only/state.json", '{"a": 1}')
        _write(plugins / "vendored-node/package.json", '{"name": "x"}')
        (plugins / "empty-dir").mkdir(parents=True, exist_ok=True)

        # a real plugin, not enabled — must be reported
        _write(plugins / "real-plugin/plugin.yaml", "name: real-plugin\nversion: 0.1.0\n")

        # a real plugin whose manifest name differs from its directory
        _write(plugins / "dir-name-differs/plugin.yaml", "name: manifest-name\nversion: 0.1.0\n")

        # an enabled plugin whose manifest name differs from its directory
        _write(plugins / "enabled-dir/plugin.yaml", "name: enabled-manifest\nversion: 0.1.0\n")

        config = home / "config.yaml"
        _write(config, "plugins:\n  enabled:\n    - enabled-manifest\n  disabled: []\n")

        checks._store().clear()
        checks._hermes_config_path = lambda: str(config)
        checks._hermes_home_from_library = lambda: str(home)
        checks._bundled_plugins_dir = lambda: None

        result = checks.check_plugins()
        detail = result.get("detail") or []
        notes = [str(d) for d in detail] if isinstance(detail, list) else [str(detail)]
        joined = " | ".join(notes)

        # (1) no manifest-less directory may appear
        for stray in ("state-only", "vendored-node", "empty-dir"):
            if stray in joined:
                failures.append(
                    f"manifest-less dir {stray!r} was reported as a plugin: {joined}"
                )

        # (2) a real un-enabled plugin is still reported
        if "real-plugin" not in joined:
            failures.append(f"real un-enabled plugin was not reported: {joined}")

        # (3) the note is keyed on the manifest name, not the directory
        if "manifest-name" not in joined:
            failures.append(f"note not keyed on manifest name: {joined}")
        if "dir-name-differs" in joined:
            failures.append(f"note used the directory basename instead of the manifest name: {joined}")

        # (4) an enabled plugin resolved by manifest name is not "missing"
        if result.get("status") == "broken":
            failures.append(f"enabled plugin wrongly reported missing: {result!r}")
        if "enabled-manifest" in joined or "enabled-dir" in joined:
            failures.append(f"enabled plugin should not appear in notes: {joined}")

        # (5) upstream manifests: an exclusive user provider is not healthy.
        mem = SimpleNamespace(
            name="mem-provider",
            key="memory/mem-provider",
            kind="exclusive",
            source="user",
            path=str(plugins / "memory" / "mem-provider"),
        )
        _write(config, "plugins:\n  enabled: [mem-provider]\n  disabled: []\n")
        checks._store().clear()
        result = checks.check_plugins(manifests=[mem])
        joined = " | ".join(str(d) for d in (result.get("detail") or []))
        if result.get("status") != "broken" or "memory.provider" not in joined:
            failures.append(f"exclusive provider verdict wrong: {result!r}")

        # (6) a bundled backend in plugins.enabled is not "missing".
        web = SimpleNamespace(
            name="web-brave-free",
            key="web/brave_free",
            kind="backend",
            source="bundled",
            path=str(Path(td) / "bundled" / "web" / "brave_free"),
        )
        _write(config, "plugins:\n  enabled: [web-brave-free]\n  disabled: []\n")
        checks._store().clear()
        result = checks.check_plugins(manifests=[web])
        joined = " | ".join(str(d) for d in (result.get("detail") or []))
        if result.get("status") == "broken" or "loads without" not in joined:
            failures.append(f"bundled backend verdict wrong: {result!r}")

        # (6a) a top-level key that differs from the manifest name still
        # counts as enabled for the opt-in note.
        keyed = SimpleNamespace(
            name="manifest-only-name",
            key="dir-key",
            kind="standalone",
            source="user",
            path=str(plugins / "dir-key"),
        )
        _write(config, "plugins:\n  enabled: [dir-key]\n  disabled: []\n")
        checks._store().clear()
        result = checks.check_plugins(manifests=[keyed])
        joined = " | ".join(str(d) for d in (result.get("detail") or []))
        if "manifest-only-name" in joined:
            failures.append(f"enabled-by-key plugin noted as opt-in: {result!r}")

        # (6c) an exclusive provider is never "opt-in".
        exclusive = SimpleNamespace(
            name="mem-quiet",
            key="memory/mem-quiet",
            kind="exclusive",
            source="user",
            path=str(plugins / "mem-quiet"),
        )
        _write(config, "plugins:\n  enabled: []\n  disabled: []\n")
        checks._store().clear()
        result = checks.check_plugins(manifests=[exclusive])
        joined = " | ".join(str(d) for d in (result.get("detail") or []))
        if "mem-quiet" in joined:
            failures.append(f"exclusive provider noted as opt-in: {result!r}")

        # (6b) a bare sub-category name is not a plugin id on either path.
        _write(config, "plugins:\n  enabled: [memory]\n  disabled: []\n")
        checks._store().clear()
        result = checks.check_plugins(manifests=[])
        if result.get("status") == "broken":
            failures.append(f"bare sub-category name reported broken: {result!r}")

        # (7) a name with no manifest is still reported missing.
        _write(config, "plugins:\n  enabled: [ghost]\n  disabled: []\n")
        checks._store().clear()
        result = checks.check_plugins(manifests=[])
        if result.get("status") != "broken":
            failures.append(f"unknown plugin not reported broken: {result!r}")

        # (8) a bundled id inside a skipped sub-category names its category,
        # not "missing" — upstream excludes those dirs from the manifest list.
        bundled = Path(td) / "bundled"
        _write(bundled / "computer_use" / "cua" / "plugin.yaml", "name: cua\n")
        checks._bundled_plugins_dir = lambda: str(bundled)
        _write(config, "plugins:\n  enabled: [cua]\n  disabled: []\n")
        checks._store().clear()
        result = checks.check_plugins(manifests=[])
        joined = " | ".join(str(d) for d in (result.get("detail") or []))
        if result.get("status") != "broken" or "computer_use" not in joined:
            failures.append(f"skipped-category plugin verdict wrong: {result!r}")
        checks._bundled_plugins_dir = lambda: None

        # (9) discovery for a DIFFERENT home must not judge this config. In CI
        # Hermes is installed, so the import succeeds — the home guard is what
        # keeps a stubbed fixture from being compared with the real profile.
        import types

        fake_pkg = types.ModuleType("hermes_cli")
        fake_pkg.__path__ = []
        fake_discovery = types.ModuleType("hermes_cli.plugins_discovery")
        fake_discovery.collect_directory_manifests = lambda: [
            SimpleNamespace(
                name="foreign-only",
                key="foreign-only",
                kind="standalone",
                source="user",
                path="/elsewhere/foreign-only",
            )
        ]
        fake_constants = types.ModuleType("hermes_constants")
        fake_constants.get_hermes_home = lambda: "/some/other/home"
        saved = {
            name: sys.modules.get(name)
            for name in ("hermes_cli", "hermes_cli.plugins_discovery", "hermes_constants")
        }
        sys.modules["hermes_cli"] = fake_pkg
        sys.modules["hermes_cli.plugins_discovery"] = fake_discovery
        sys.modules["hermes_constants"] = fake_constants

        _write(config, "plugins:\n  enabled: [real-plugin]\n  disabled: []\n")
        checks._store().clear()
        result = checks.check_plugins()
        if result.get("status") == "broken":
            failures.append(f"foreign-home discovery judged this config: {result!r}")

        # (10) the matching home uses the loader's manifests (the live path).
        fake_constants.get_hermes_home = lambda: str(home)
        fake_discovery.collect_directory_manifests = lambda: [
            SimpleNamespace(
                name="web-brave-free",
                key="web/brave_free",
                kind="backend",
                source="bundled",
                path=str(Path(td) / "bundled" / "web" / "brave_free"),
            )
        ]
        _write(config, "plugins:\n  enabled: [web-brave-free]\n  disabled: []\n")
        checks._store().clear()
        result = checks.check_plugins()
        joined = " | ".join(str(d) for d in (result.get("detail") or []))
        if result.get("status") == "broken" or "loads without" not in joined:
            failures.append(f"matching-home discovery not used: {result!r}")

        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    if failures:
        for f in failures:
            print(f"FAIL: {f}", file=sys.stderr)
        return 1

    print("OK: only manifest-bearing plugin dirs are reported (F2)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
