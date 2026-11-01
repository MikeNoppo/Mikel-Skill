---
name: session-report
description: Tulis laporan sesi HTML (apa yang dibuat dan kenapa, status siap commit/PR, keputusan tertunda, code review, pengujian) ke /tmp/session-reports.
disable-model-invocation: true
allowed-tools: Read Edit(//tmp/session-reports/**) Bash(python3 /home/mikel/.agents/skills/session-report/scripts/render.py *)
---

# Session report

The developer reviews agent work through this report instead of scrolling the chat: the agent builds, the developer decides. Write for a reviewer who has ten seconds first and ten minutes later. The reading order is fixed: the **verdict** (can this ship?), then the **decisions** waiting on the developer, then what changed and **why**, then the **evidence**.

You write data only: one `report.json` that matches `assets/report.schema.json`. `scripts/render.py` owns everything else: the HTML layout, the git facts (branches, commits, per-file diffs, push state), screenshot embedding, `index.html` and the desktop notification. That split keeps every report consistent, so the HTML always comes from the renderer.

## Modes

| Mode | You are here when | Session id |
|---|---|---|
| Manual | The user typed `/session-report` (Claude Code) or `$session-report` (Codex) | Claude Code: `${CLAUDE_SESSION_ID}`. Codex: `auto` |
| Background (Claude fork) | You are a forked subagent and your prompt names this mode | Given in the prompt |
| Background (Codex) | You run inside `codex exec fork` with a read-only sandbox and an output schema | Given in the prompt |

In both background modes the developer is not watching: finish without asking anything.

In Background (Codex), when the session's last assistant message asks the user something they must answer before the task can continue, return `"skip": true` with the other fields minimal but valid. A closing offer such as "mau saya commit?" or "mau saya buka PR?" means the task is finished, so report it normally.

## Steps

1. **Gather evidence** from the whole session, not only the last turn. Done when you can account for every task the user asked for (finished, partial or not started), every file changed and why, every command that verified something together with its actual result, every code review finding and what happened to it, and every assumption made without asking. The conversation is the primary source; read code or run read-only git commands only to fill gaps.
2. **Write the data.** Read [REPORT-DATA.md](REPORT-DATA.md) for every field, the status rules and the code review mapping, then fill all fields. Write in Indonesian, address the developer as "kamu", keep technical terms in English (endpoint, middleware, token), and prefer plain words over jargon.
   - Manual and Background (Claude fork): write a new file `/tmp/session-reports/<session-id>/report-<YYYYmmdd-HHMMSS>.json`. Use a fresh name every time; the renderer takes the path you give it.
   - Background (Codex): the JSON is your final answer. Stop after this step.
3. **Render**: `python3 /home/mikel/.agents/skills/session-report/scripts/render.py <session-id> <json-path> --harness <claude|codex>`. Add `--open` in Manual mode so the report opens right away. Exit code 2 lists schema errors: fix them in a new file and render again. Done when it prints the HTML path.
4. **Reply** with exactly one line: `Laporan sesi: <html-path>`.
