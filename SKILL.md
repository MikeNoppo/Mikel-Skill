---
name: session-report
description: Buat atau perbarui laporan sesi HTML secara manual, berisi hasil kerja, implementasi, status, diagram, dan bukti pengujian.
disable-model-invocation: true
---

# Session report

Run only when the user invokes `/session-report` (Claude Code), `$session-report` (Codex), or explicitly asks to create/update this report. Work in the current conversation, using its model and effort. Complete the report in the foreground without starting a subagent, copied session, background worker, or queued chat message.

Write in Indonesian, address the developer as "kamu", and keep familiar technical terms in English. Lead with readiness and pending decisions, followed by what changed, why, implementation, diagrams and evidence. The model writes JSON; the renderer owns the fixed HTML design and git facts.

## Create or update

1. Run `python3 /home/mikel/.agents/skills/session-report/scripts/prepare.py auto --harness <claude|codex>`. It returns `session_id`, `data_path`, `previous_data`, and `html`. If the harness environment lacks its session ID, obtain the actual ID from session context and pass it explicitly. Never select another session's report just because it is newest or shares a repository.
2. If `previous_data` exists, read it before writing. If only `html` exists, read that report instead. Update the same session's cumulative account: preserve relevant earlier work and old flow diagrams, resolve stale statuses, and add subsequent changes and verification. An existing report in a different session stays separate unless the user explicitly asks to update it; in that case use its session ID.
3. Gather evidence from the entire conversation, filling gaps with read-only code/git inspection. Account for requested work, implementation, current completion/blockers, tests actually run, and known limitations. List session files explicitly in `repos[].files`. Include `repos[].commits` only for exact full commit hashes proven to have been created during this session; do not infer ownership from branch history, author or dates. Explain missing historical evidence rather than inventing it.
4. Read [REPORT-DATA.md](REPORT-DATA.md), then write valid JSON to the returned `data_path` (`report.json`, reused on subsequent calls). Use the schema in `assets/report.schema.json`. Set `skip` to `false`.
   Code review is optional: read the session to determine whether a review was invoked or its results were provided. If so, summarize findings and their latest dispositions. Otherwise set `code_review` to `{"ran": false, "source": "", "findings": []}`; omit review checklist items and do not lower readiness merely because no review ran. Creating a report does not request a new review or additional tests.
5. Run `python3 /home/mikel/.agents/skills/session-report/scripts/render.py <session_id> <data_path> --harness <claude|codex> --open`. The renderer reuses the recorded HTML path, refreshes git state and updates `latest.html` and `index.html`. Exit 2 means invalid report data: correct it and retry. Exit 1 means a path, identity or environment problem: fix that cause. Finish when it prints the HTML path.
6. Reply: `Laporan sesi: [Buka laporan](<html-path>)`.
