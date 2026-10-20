"""Single source of truth for names/values that drift across Hermes versions.

Update THIS file (and only this file) when a `hermes` subcommand or config field
is renamed upstream. CI should diff these against live `hermes ...` output.
Do not scatter these strings across checks.py or __init__.py.
"""

# Top-level config key for MCP servers
CONFIG_MCP_SERVERS = "mcp_servers"

# Top-level config key for the built-in memory section (memory.provider,
# memory.memory_char_limit, ...). Also a plugin sub-category dir name — the F3
# guard forbids it as a literal in checks.py, so it lives here.
CONFIG_MEMORY_SECTION = "memory"

# Top-level foreign key indicating a Claude-Code-style paste (silently NOT read by Hermes).
# (Dropped the dead `"mcp.servers"` entry: `key in data` only matches top-level
# keys, so a dotted name never matched the nested `mcp.servers` it was meant for.)
FOREIGN_MCP_KEYS = ("mcpServers",)

# Skill frontmatter OS gate (agent/skill_utils.py::skill_matches_platform).
# Also a plugin sub-category dir name, which the F3 guard forbids as a literal
# in checks.py — reference it from here.
SKILL_PLATFORMS_KEY = "platforms"

# MCP server shape requirements (per entry): stdio needs `command`, http needs `url`
MCP_STDIO_KEY = "command"
MCP_HTTP_KEY = "url"

# MCP facts that drift across Hermes versions. Verified 2026-09 against Hermes
# v0.21.0 (commit 63279301). Upstream sources: tools/mcp_tool.py through
# v2026.8.31; after the 2026-09 refactor, tools/mcp_tool_schema.py (prefix) and
# tools/mcp_tool_common.py (tool-call timeout). These are checked against
# upstream main by tools/check_upstream_drift.py (DRIFT_FACTS) — update them
# here and in skills/diagnosing-mcp/SKILL.md together when they change upstream.
MCP_TOOL_NAME_PREFIX = "mcp__"       # native MCP tool-name prefix: mcp__<server>__<tool>
MCP_TIMEOUT_DEFAULT = 300            # per-tool-call timeout default, seconds
MCP_CONNECT_TIMEOUT_DEFAULT = 60     # initial connection timeout default, seconds

# Upstream project_venv_dir() candidate order (hermes_constants.py) — its
# docstring: "``venv`` wins when both exist, matching what the installers
# write." skills/diagnosing-path/SKILL.md and references/venv_detection_patterns.py
# mirror this order; tools/check_upstream_drift.py asserts it against upstream.
PROJECT_VENV_ORDER = '"venv", ".venv"'

# Built-in memory stores (tools/memory_tool.py: get_memory_dir() -> $HERMES_HOME/memories/).
# Entry delimiter and default char limits drift upstream — verified 2026-09
# against hermes-agent commit 8d3745a99b (defaults in cli-config.yaml.example /
# hermes_cli/config_defaults.py). check_memory_hygiene() in checks.py consumes
# these; tools/check_upstream_drift.py (DRIFT_FACTS) asserts the delimiter and
# limits against upstream main, where the delimiter lives in
# tools/memory_tool_store.py (moved there by the 2026-09 refactor).
# Canonical install source for the skills tap, derived from plugin.yaml
# `homepage` (https://github.com/iap/hermes-guide). Used by check_skills'
# install-nudge so a fork or rename does not silently break the suggested
# command. Mirrors homepage; update both together.
SKILLS_INSTALL_SOURCE = "iap/hermes-guide"

BUILTIN_MEMORY_STORES = ("MEMORY.md", "USER.md")
MEMORY_ENTRY_DELIMITER = "§"
MEMORY_CHAR_LIMIT_DEFAULT = 2200
USER_CHAR_LIMIT_DEFAULT = 1375

# Plugin sub-category directories that use their own discovery/selection keys
# (memory.provider / context.engine / image_gen.provider / --provider) — NOT plugins.enabled.
PLUGIN_SUBCATEGORY_DIRS = (
    "platforms",
    "memory",
    "context_engine",
    "model-providers",
    "image_gen",
    "video_gen",
    "web",
    "browser",
    "cron_providers",
    # Added in v2026.9.11 — these subcategories use their own selection keys,
    # not plugins.enabled. Verified against upstream plugins/ directory.
    # NOTE: hermes-achievements and kanban are NOT subcategories — they contain
    # standalone plugins gated by plugins.enabled (verified by T-Rex in #74).
    # Same for disk-cleanup, google_meet, security-guidance and teams_pipeline:
    # each ships its own plugin.yaml at plugins/<name>/plugin.yaml, so the
    # loader sees them as plugins, not as a provider directory.
    # `observability` was listed here from v2026.9.11 until 2026-10-19 and is
    # NOT upstream: `plugins/observability/` does not exist at baseline
    # d97007c or at upstream main, and no commit in the fetched history ever
    # added it. Dropped rather than kept as a harmless extra, because a pinned
    # name that upstream never had is a fact the check cannot verify.
    "dashboard_auth",
    # computer_use: "Computer-use provider discovery", bundled
    # `plugins/computer_use/<name>/` plus the built-in `cua` driver
    # (plugins/computer_use/__init__.py). No plugin.yaml, own selection key --
    # same shape as the entries above. Without this the scan collected
    # `computer_use/cua` as a discoverable plugin id, so a stale
    # `plugins.enabled: [cua]` resolved as valid instead of being flagged.
    "computer_use",
)

# Filesystem names owned by the Hermes layout (rename upstream -> edit here).
CONFIG_FILENAME = "config.yaml"
HOOKS_ALLOWLIST_FILENAME = "shell-hooks-allowlist.json"
BUNDLED_SKILLS_MANIFEST = ".bundled_manifest"
SKILL_BUNDLES_DIRNAME = "skill-bundles"

# `hermes hooks doctor` output wording this check parses (reword upstream ->
# edit here, not a regex in checks.py).
HOOKS_DOCTOR_NONE_CONFIGURED = "No shell hooks configured"
HOOKS_DOCTOR_HEALTHY_SUMMARY = "All shell hooks look healthy"
HOOKS_DOCTOR_MARKER_RE = r"\s+[✗⚠]"

# Hermes CLI argv vectors (subcommand rename upstream -> edit here).
CLI_CONFIG_PATH_ARGV = ("config", "path")
CLI_HOOKS_DOCTOR_ARGV = ("hooks", "doctor")

# plugins.* config keys (symmetric with CONFIG_MCP_SERVERS above).
CONFIG_PLUGINS_SECTION = "plugins"
CONFIG_PLUGINS_ENABLED = "enabled"
CONFIG_PLUGINS_DISABLED = "disabled"

# Check-scope -> diagnosing skill: rendered in proactive boundary logs so a
# drift finding names what to load next (read-only string, no behavior).
SKILL_FOR_SCOPE = {
    "config": "hermes-configuration-guide",
    "mcp": "diagnosing-mcp",
    "skills": "diagnosing-skills",
    "commands": "diagnosing-commands",
    "hooks": "diagnosing-hooks",
    "plugins": "diagnosing-plugins",
    "memories": "diagnosing-memory",
    "sessions": "diagnosing-triage",
    "update": "diagnosing-cli-tui",
}

# Near-duplicate detection budget: entries beyond this count skip the pairwise
# pass (reported as truncated) so an over-limit store cannot stall a session
# boundary with O(n^2) comparisons.
MEMORY_NEAR_DUP_ENTRY_CAP = 400

# Credential-pool facts (drift-watched against upstream main; asserted by
# diagnosing-providers Step 5 and the configuration guide's Credential pool
# section).
CREDENTIAL_POOL_SIBLING_START = 2
CREDENTIAL_POOL_CUSTOM_PREFIX = "custom:"
