# Verification section template

Use this scaffold for the `## Verification` (or `## Apply and verify`) section of
every `diagnosing-*` skill. Keep it concrete: commands a user can paste, not
prose.

## Template

```markdown
## Verification

After applying the fix:

1. Re-run the failing scenario / diagnostic command to confirm the symptom is
   resolved.
2. Re-run the relevant `hermes ...` command(s) and confirm the expected state.
3. Check logs/config (`$HERMES_HOME/logs/`, `$HERMES_HOME/config.yaml`) for the
   expected state with no new errors.
4. If the issue was environment-specific, confirm it works in your actual setup.

Commands:

\`\`\`bash
# Replace with the skill's actual verification commands.
hermes ...
\`\`\`
```

## Rules

- One `## Verification` (or `## Apply and verify`) section per diagnostic skill.
- At least one concrete command or check; no "verify it works" without a
  command.
- Place it after the fix guidance and before `## Report`.
- Do not duplicate the `## Report` template; verification is operational, Report
  is presentational.
```
