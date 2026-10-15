# Symptom → Skill mapping table

Comprehensive mapping from specific symptoms to the target diagnostic skill. When the user's description matches a row, load that skill directly.

| Symptom | Target skill |
|---|---|
| Agent keeps repeating itself / "looping again" / same tool calls every turn | diagnosing-triage (§1b runaway branch) |
| "Could not fetch from any source" / "Could not find … in any source" | diagnosing-auth |
| GitHub 401 on hub installs | diagnosing-auth |
| Rate-limit 403 during installs | diagnosing-auth |
| `hermes skills install` / `hermes plugins install` fails | diagnosing-auth |
| Bots not appearing in chat | diagnosing-bot-mode |
| Profile conflicts between bots | diagnosing-bot-mode |
| Bot-to-bot messaging broken | diagnosing-bot-mode |
| CDP connection failures | diagnosing-browser |
| Chrome 144+ compatibility | diagnosing-browser |
| Playwright errors | diagnosing-browser |
| agent-browser not working | diagnosing-browser |
| CLI glitches / rendering artifacts (native Windows) | diagnosing-cli-tui |
| Themes / skins not applying (native Windows) | diagnosing-cli-tui |
| Busy indicators unreadable (native Windows) | diagnosing-cli-tui |
| Mouse modes not working (native Windows) | diagnosing-cli-tui |
| Encoding / mojibake issues (native Windows) | diagnosing-cli-tui |
| CLI/TUI issues on POSIX/WSL | `hermes doctor` + the `display:` block of `config.yaml` (no dedicated skill yet — do not load diagnosing-cli-tui) |
| Missing slash commands | diagnosing-commands |
| Overridden slash commands | diagnosing-commands |
| Skills-as-commands not appearing | diagnosing-commands |
| Skill bundles not loading | diagnosing-commands |
| Cron not firing | diagnosing-cron |
| Scheduler dead / wedged | diagnosing-cron |
| Fire-claim stuck | diagnosing-cron |
| Timezone wrong | diagnosing-cron |
| Desktop app won't launch | diagnosing-desktop |
| npm errors on desktop | diagnosing-desktop |
| Blank window on launch | diagnosing-desktop |
| Electron crash | diagnosing-desktop |
| Bot not responding on platform | diagnosing-gateway first (`hermes gateway status`); diagnosing-bot-mode only if the gateway is healthy |
| Platform allowlist issues | diagnosing-gateway |
| Token validation failures | diagnosing-gateway |
| Hooks not firing | diagnosing-hooks |
| Gateway HOOK.yaml errors | diagnosing-hooks |
| Plugin hooks broken | diagnosing-hooks |
| Shell hooks not executing | diagnosing-hooks |
| High system load during agent operation | diagnosing-host-pressure |
| OOM kills | diagnosing-host-pressure |
| Plugin discards after load timeout | diagnosing-host-pressure |
| Resource exhaustion | diagnosing-host-pressure |
| MCP won't connect | diagnosing-mcp |
| MCP tools not appearing | diagnosing-mcp |
| MCP OAuth failures | diagnosing-mcp |
| MCP config errors | diagnosing-mcp |
| Agent forgot something | diagnosing-memory |
| Memory provider down | diagnosing-memory |
| MEMORY.md errors | diagnosing-memory |
| USER.md errors | diagnosing-memory |
| Path / venv confusion | diagnosing-path |
| Dual-venv layout issues | diagnosing-path |
| Wrong Python interpreter | diagnosing-path |
| Plugin not loading | diagnosing-plugins |
| Plugin not enabled | diagnosing-plugins |
| plugins.enabled gate blocking | diagnosing-plugins |
| Provider picker flooded | diagnosing-providers |
| discover_models misbehaving | diagnosing-providers |
| Provider auth failures | diagnosing-providers |
| Model catalog bloat | diagnosing-providers |
| Skills not discovered | diagnosing-skills |
| Skills shadowed | diagnosing-skills |
| Skills hidden | diagnosing-skills |
| Skills stuck "user-modified" | diagnosing-skills |
| STT/TTS failures | diagnosing-voice |
| Audio device not found | diagnosing-voice |
| Voice latency | diagnosing-voice |
| ffmpeg errors | diagnosing-voice |
| "Where is X configured?" | hermes-configuration-guide |
| Install / reinstall / upgrade / uninstall | installing-hermes |
