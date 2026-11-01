# report.json fields

Every field in `assets/report.schema.json` is required. Use `[]`, `""` or `null` (where the schema allows it) for what does not apply; the renderer hides empty optional sections and shows an explicit "nothing here" note for core ones. A complete example lives in `test/fixtures/report.json`.

Text fields accept two inline marks: `` `code` `` and `**bold**`. Newlines become line breaks. Everything else is escaped.

## Evidence rule

A claim is only as strong as what happened in this session. "Lulus" means the command ran in this session and you saw its output pass. A command you did not run is `not_run` or `skip`, never `pass`. When the session's own messages disagree with the files on disk, trust the disk and say so.

## Verdict

| Field | Meaning |
|---|---|
| `skip` | `true` only in Background (Codex) when the session is waiting on the user's answer. Otherwise `false`. |
| `title` | The work in a few words, named after what the user asked for ("MFA di auth module BE"). |
| `summary` | Two or three sentences: what was asked, what exists now, what is left. |
| `status` | `siap`: every requested task done, verification ran and passed, no unresolved review finding, no pending decision that blocks the PR. `hampir`: done, but something is missing before the PR (a test not run, review not run, an open finding, a pending decision). `sebagian`: part of the requested scope is not built yet. `blocked`: cannot continue without something external (a credential, a decision, a broken environment). |
| `status_note` | One sentence that justifies the status, read next to the status badge. |
| `pills` | Two to five short key facts for the header ("TOTP + 10 recovery code", "Belum di-push"). |
| `extra_stats` | Optional number cards beyond the four the renderer computes (pending decisions, files, commits, review findings). Example: `{"value": "42", "label": "test BE lulus"}`. |
| `checklist` | Readiness items with `state` `ok` / `warn` / `bad` / `skip` and the evidence ("`go test ./...` dijalankan 23:41, 42 lulus"). Cover tests, build, lint/typecheck, code review, and anything the repo's own rules require. Commit and push state come from git in the renderer, so they stay out of the checklist. |

## Butuh keputusanmu

`decisions` is the most important list in the report: everything the developer has to decide before the work is final. Include open questions, assumptions you made without asking (`asumsi`), review findings that still need validation (`validasi`), and trade-offs that need approval (`tradeoff`). `pertanyaan` is for a question still waiting for an answer. Each item gets the context in one or two sentences, the concrete `options`, and your `recommendation`. An item may also appear in the code review or trade-off tables; here it is phrased as the decision. An empty list renders as "Tidak ada keputusan tertunda", so leave it empty only when that is true.

## Apa yang dibuat & kenapa

- `built`: one card per user-visible change: `what` in plain language, `why` the reason it exists or was done this way.
- `key_decisions`: decisions already settled in the session (topic, decision, reason), so the reviewer sees what was chosen without rereading the chat.

## Diagrams

All diagrams are Mermaid source in `{"mermaid": ..., "explanation": ...}`. The renderer themes them for light and dark mode.

- `architecture`: a `flowchart LR` of the components this work touched and how data moves between them. Use it when the work spans two or more components; otherwise `null`.
- `flows`: one entry per user-facing or request flow. Use `sequenceDiagram` for request/response flows and `flowchart` for decision logic. Set `before` only when an existing flow changed: `before` shows how it worked, `after` how it works now, each with an explanation of how it works. A brand-new flow has `before: null`.
- `lifecycle`: a `stateDiagram-v2` for an entity whose states can be traced (a token, a challenge, a session, an ID, an order status). Leave it empty for work without such an entity.

In flowcharts, mark nodes with `:::baru` (added), `:::ubah` (changed) or `:::hapus` (removed); the renderer supplies those classes and a legend. Keep a diagram to roughly twelve nodes, label in Indonesian, and wrap labels containing parentheses, slashes or quotes in `["..."]`.

## Per repo and files

`repos` has one entry per repository the session touched. `path` is the repo root (absolute is safest). `summary` and `notes` describe the implementation in that repo. `files` lists every file changed in the session with a one-line `reason`. The renderer adds the change type, the line counts, the commits and the diff from git; a file git does not show as changed is dropped, and files outside any git repo are listed without a diff.

## Code review

`code_review.ran` is `true` when any review ran in the session; `source` names it (`/code-review (xhigh)`, mattpocock `code-review`, Codex `/review`). Each finding gets a `status`:

| Situation | `status` |
|---|---|
| `/code-review` reported `outcome: fixed`, or the fix was made and verified later in the session | `fixed` |
| `outcome: skipped`, or the developer chose not to fix it | `not_fixed` (put the reason in `resolution`) |
| `outcome: no_change_needed`, or it was judged acceptable as is | `accepted` (reason in `resolution`) |
| `verdict: PLAUSIBLE` and nobody confirmed or fixed it | `needs_validation` (also add a `validasi` decision) |
| Reported but never acted on | `open` |

`evidence` names what proves a fix (`unit test`, `integration test`, `build`, `analisis`).

## Testing

`tests` has one row per verification layer that actually ran (unit, integration, contract, lint, typecheck, build), with the exact `command`, the `result` and counts in `detail`. Leave it empty when nothing ran; the renderer then warns that there is no automated evidence.

`e2e` is `null` unless an end-to-end test ran in the session. `environment` says what was stood up. `scenarios` summarises outcomes. `steps` walks through the run in order:

- UI step: `action` is what the user does, `observed` what appeared, and `screenshot` the absolute path of a screenshot file the session produced.
- API-only step: `action` is the request (method, endpoint, relevant input), `expected` and `observed` are the status code plus the fields or events checked, and `screenshot` is `""`.

## Closing

- `tradeoffs`: known trade-offs and risks with `level` `perhatian` / `sedang` / `rendah` / `temuan_lama` (an existing problem the session ran into, not caused by it).
- `out_of_scope`: work deliberately left out that could become its own session: the item, why it matters, and a self-contained `prompt` the developer can paste into a new session (repo, goal, relevant context).
- `next_steps`: what the developer does next, in order: decisions to make, what to review, push and PR, env vars or secrets, migrations, manual checks, deploy notes. Steps for the agent belong in `out_of_scope`.
