import argparse
import base64
import html
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import common

HARNESS = {"claude": "Claude Code", "codex": "Codex"}
STATUS = {
    "siap": ("Siap commit & PR", "ok"),
    "hampir": ("Hampir siap", "warn"),
    "sebagian": ("Setengah jalan", "warn"),
    "blocked": ("Blocked", "bad"),
}
CHECK = {"ok": ("✓", "ok"), "warn": ("!", "warn"), "bad": ("✗", "bad"), "skip": ("–", "info")}
DECISION = {
    "pertanyaan": ("Pertanyaan terbuka", "info", "d-info"),
    "asumsi": ("Asumsi agent", "warn", ""),
    "validasi": ("Perlu validasi", "warn", ""),
    "tradeoff": ("Trade-off perlu disetujui", "bad", "d-bad"),
}
FINDING = {
    "fixed": ("Sudah diperbaiki", "ok"),
    "not_fixed": ("Tidak diperbaiki", "bad"),
    "accepted": ("Dibiarkan", "info"),
    "needs_validation": ("Perlu validasi", "warn"),
    "open": ("Belum ditindaklanjuti", "warn"),
}
RESULT = {"pass": ("lulus", "ok"), "fail": ("gagal", "bad"), "partial": ("sebagian", "warn"), "not_run": ("tidak dijalankan", "info")}
LEVEL = {"perhatian": ("perhatian", "bad"), "sedang": ("sedang", "warn"), "rendah": ("rendah", "info"), "temuan_lama": ("temuan lama", "info")}
FILE_STATUS = {"A": ("baru", "ok"), "M": ("diubah", "info"), "D": ("dihapus", "bad"), "T": ("diubah", "info"), "?": ("di luar git", "info")}
DAYS = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
MONTHS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
DIFF_LINES = 400
SHOT_BYTES = 6 * 1024 * 1024
GLYPH = "\U000F0219"
INLINE_CODE = re.compile(r"`([^`\n]+)`")
BOLD = re.compile(r"\*\*(.+?)\*\*")
DIAGRAM_CLASS = re.compile(r":::(baru|ubah|hapus)\b")


class ReportError(Exception):
    pass


def type_matches(value, expected):
    names = expected if isinstance(expected, list) else [expected]
    return any(isinstance(value, TYPES[name]) and not (name != "boolean" and isinstance(value, bool)) for name in names)


def type_name(value):
    for name, kind in TYPES.items():
        if isinstance(value, kind):
            return name
    return type(value).__name__


def resolve(schema, defs):
    while "$ref" in schema:
        schema = defs[schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def validate(value, schema, defs, path="$"):
    schema = resolve(schema, defs)
    if "anyOf" in schema:
        options = [resolve(option, defs) for option in schema["anyOf"]]
        attempts = [validate(value, option, defs, path) for option in options]
        if any(not errors for errors in attempts):
            return []
        relevant = [errors for option, errors in zip(options, attempts) if type_matches(value, option.get("type", "null"))]
        return min(relevant or attempts, key=len)
    expected = schema.get("type")
    if expected and not type_matches(value, expected):
        return [f"{path}: expected {expected}, got {type_name(value)}"]
    errors = []
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} is not one of {schema['enum']}")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        errors += [f"{path}: missing field {key}" for key in schema.get("required", []) if key not in value]
        for key, item in value.items():
            if key in properties:
                errors += validate(item, properties[key], defs, f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unknown field {key}")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            errors += validate(item, schema["items"], defs, f"{path}[{index}]")
    return errors


def load_report(path):
    try:
        report = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ReportError(f"cannot read {path}: {error}")
    schema = json.loads(common.SCHEMA.read_text())
    errors = validate(report, schema, schema.get("$defs", {}))
    if errors:
        raise ReportError("\n".join(errors[:40]))
    return report


def e(text):
    return html.escape(str(text), quote=True)


def rich(text):
    escaped = html.escape(str(text), quote=False)
    escaped = INLINE_CODE.sub(lambda match: f"<code>{match.group(1)}</code>", escaped)
    escaped = BOLD.sub(r"<b>\1</b>", escaped)
    return escaped.replace("\n", "<br>")


def tag(label, cls):
    return f'<span class="tag {cls}">{e(label)}</span>'


def long_date(moment):
    return f"{DAYS[moment.weekday()]}, {moment.day} {MONTHS[moment.month - 1]} {moment.year} · {moment:%H:%M}"


def number(value):
    return int(value) if str(value).isdigit() else 0


def relative(path, repo):
    try:
        return str(Path(os.path.realpath(path)).relative_to(Path(os.path.realpath(repo))))
    except ValueError:
        return None


def lines_of(text):
    return [line for line in (text or "").splitlines() if line]


def name_status(repo, base):
    statuses = {}
    for line in lines_of(common.git(repo, "diff", "--name-status", "--no-renames", base)):
        letter, _, path = line.partition("\t")
        statuses[path] = letter[:1]
    return statuses


def numstat(repo, *args):
    stats = {}
    for line in lines_of(common.git(repo, "diff", "--numstat", "--no-renames", *args, ok=(0, 1))):
        parts = line.split("\t", 2)
        if len(parts) == 3:
            stats[parts[2]] = (parts[0], parts[1])
    return stats


def file_diff(repo, base, rel, untracked):
    if untracked:
        text = common.git(repo, "diff", "--no-index", "--", "/dev/null", rel, ok=(0, 1))
    else:
        text = common.git(repo, "diff", "--no-renames", base, "--", rel)
    lines = (text or "").splitlines()
    return lines[:DIFF_LINES], len(lines) > DIFF_LINES


def repo_facts(repo, base, session_paths):
    head = common.git(repo, "rev-parse", "--verify", "-q", "HEAD")
    base = base or head or EMPTY_TREE
    upstream = common.git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    ahead = behind = None
    if upstream:
        counts = (common.git(repo, "rev-list", "--left-right", "--count", "@{u}...HEAD") or "").split()
        if len(counts) == 2:
            behind, ahead = int(counts[0]), int(counts[1])
    commits, committed = [], set()
    if head and base != head:
        span = "HEAD" if base == EMPTY_TREE else f"{base}..HEAD"
        commits = [line.split("\t", 1) for line in lines_of(common.git(repo, "log", "--reverse", "--format=%h%x09%s", span)) if "\t" in line]
        committed = set(lines_of(common.git(repo, "diff", "--name-only", "--no-renames", base, "HEAD")))
    fresh = set(lines_of(common.git(repo, "ls-files", "--others", "--exclude-standard")))
    dirty = fresh | (set(lines_of(common.git(repo, "diff", "--name-only", "--no-renames", "HEAD"))) if head else set(name_status(repo, EMPTY_TREE)))
    statuses = name_status(repo, base)
    stats = numstat(repo, base)
    files = []
    for rel in sorted(committed | set(session_paths)):
        untracked = rel in fresh
        if untracked:
            added, deleted = next(iter(numstat(repo, "--no-index", "--", "/dev/null", rel).values()), ("0", "0"))
            status = "A"
        elif rel in statuses:
            added, deleted = stats.get(rel, ("0", "0"))
            status = statuses[rel]
        else:
            continue
        diff, truncated = file_diff(repo, base, rel, untracked)
        files.append({"path": rel, "status": status, "added": added, "deleted": deleted, "diff": diff, "truncated": truncated, "dirty": rel in dirty})
    return {
        "root": repo,
        "name": Path(repo).name,
        "git": True,
        "branch": common.git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "?",
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "commits": commits,
        "files": files,
    }


def collect(sid, report, meta, cwd):
    order, paths, reasons, notes = [], {}, {}, {}
    outside = {}

    def add_repo(root):
        if root not in paths:
            order.append(root)
            paths[root] = set()
            reasons[root] = {}

    for item in report["repos"]:
        raw = item["path"] if os.path.isabs(item["path"]) else os.path.join(cwd, item["path"])
        root = common.repo_root(raw)
        if root is None:
            for entry in item["files"]:
                full = entry["path"] if os.path.isabs(entry["path"]) else os.path.join(raw, entry["path"])
                outside[os.path.normpath(full)] = entry["reason"]
            notes.setdefault(None, []).append(item)
            continue
        add_repo(root)
        notes.setdefault(root, []).append(item)
        for entry in item["files"]:
            full = entry["path"] if os.path.isabs(entry["path"]) else os.path.join(raw, entry["path"])
            rel = relative(full, root) or relative(os.path.join(root, entry["path"]), root)
            if rel:
                reasons[root][rel] = entry["reason"]
                paths[root].add(rel)
    for root in meta.get("repos", {}):
        add_repo(root)
    for event in common.events(sid):
        if event.get("kind") != "edit" or not event.get("path"):
            continue
        root = event.get("repo")
        if root:
            add_repo(root)
            rel = relative(event["path"], root)
            if rel:
                paths[root].add(rel)
        else:
            outside.setdefault(os.path.normpath(event["path"]), "")
    groups = []
    for root in order:
        if not Path(root).is_dir():
            continue
        facts = repo_facts(root, meta.get("repos", {}).get(root, {}).get("base"), paths[root])
        for entry in facts["files"]:
            entry["reason"] = reasons[root].get(entry["path"], "")
        facts["items"] = notes.get(root, [])
        groups.append(facts)
    if outside or notes.get(None):
        groups.append({
            "root": "",
            "name": "Di luar git",
            "git": False,
            "commits": [],
            "items": notes.get(None, []),
            "files": [
                {"path": path, "status": "?", "added": "", "deleted": "", "diff": [], "truncated": False, "dirty": False, "reason": reason}
                for path, reason in sorted(outside.items())
            ],
        })
    return groups


def section(anchor, title, body, lead=""):
    lead_html = f'<p class="lead">{rich(lead)}</p>' if lead else ""
    return anchor, title, f'<section id="{anchor}"><h2>{e(title)}</h2>{lead_html}{body}</section>'


def diagram(item):
    explanation = f'<p class="explain">{rich(item["explanation"])}</p>' if item["explanation"] else ""
    return f'<div class="diagram"><pre class="mermaid">{e(item["mermaid"])}</pre></div>{explanation}'


def legend(*items):
    used = {match for item in items if item for match in DIAGRAM_CLASS.findall(item["mermaid"])}
    labels = [("baru", "baru", "ok"), ("ubah", "diubah", "info"), ("hapus", "dihapus", "bad")]
    shown = [tag(label, cls) for key, label, cls in labels if key in used]
    return f'<div class="legend"><span class="muted">Warna node:</span>{"".join(shown)}</div>' if shown else ""


def totals(groups):
    files = [entry for group in groups for entry in group["files"]]
    return len(files), sum(number(f["added"]) for f in files), sum(number(f["deleted"]) for f in files)


def git_state(group):
    if not group["git"]:
        return tag("tanpa git", "info")
    tags = []
    if group["commits"]:
        tags.append(tag(f"{len(group['commits'])} commit", "ok"))
    dirty = sum(1 for entry in group["files"] if entry["dirty"])
    if dirty:
        tags.append(tag(f"{dirty} file belum di-commit", "warn"))
    if group["commits"]:
        if not group["upstream"]:
            tags.append(tag("belum ada upstream", "info"))
        elif group["ahead"]:
            tags.append(tag(f"{group['ahead']} commit belum di-push", "warn"))
        else:
            tags.append(tag("sudah di-push", "ok"))
    return " ".join(tags) or tag("tidak ada perubahan tersisa", "info")


def header(report, groups, harness, moment):
    label, cls = STATUS[report["status"]]
    names = " · ".join(group["name"] for group in groups if group["git"])
    eyebrow = f"Laporan sesi · {long_date(moment)} · {HARNESS[harness]}" + (f" · {names}" if names else "")
    pills = "".join(f'<span class="pill">{rich(pill)}</span>' for pill in report["pills"])
    pending = len(report["decisions"])
    if pending:
        pills = f'<a class="pill alert" href="#keputusan">{pending} keputusan menunggu kamu</a>' + pills
    note = f"<span>{rich(report['status_note'])}</span>" if report["status_note"] else ""
    return (
        f'<header><div class="wrap"><div class="eyebrow">{e(eyebrow)}</div><h1>{e(report["title"])}</h1>'
        f'<div class="verdict"><span class="status {cls}">{e(label)}</span>{note}</div>'
        f'<div class="pills">{pills}</div></div></header>'
    )


def summary_section(report, groups):
    count, added, deleted = totals(groups)
    review = report["code_review"]
    fixed = sum(1 for finding in review["findings"] if finding["status"] == "fixed")
    stats = [
        (str(len(report["decisions"])), "keputusan menunggu kamu"),
        (str(count), f"file berubah · +{added} / −{deleted}"),
        (str(sum(len(group["commits"]) for group in groups)), "commit di sesi ini"),
        (f"{fixed}/{len(review['findings'])}", "temuan review diperbaiki") if review["ran"] else ("–", "belum ada code review"),
    ] + [(stat["value"], stat["label"]) for stat in report["extra_stats"]]
    cards = "".join(f'<div class="stat"><b>{e(value)}</b><span>{rich(label)}</span></div>' for value, label in stats)
    body = f'<div class="grid g4">{cards}</div>'
    if groups:
        rows = []
        for group in groups:
            files, plus, minus = totals([group])
            branch = f'<code>{e(group["branch"])}</code>' + (f' <span class="muted">→ {e(group["upstream"])}</span>' if group.get("upstream") else "") if group["git"] else "–"
            rows.append(f'<tr><td>{e(group["name"])}</td><td>{branch}</td><td class="mono">{files} file · +{plus} / −{minus}</td><td>{git_state(group)}</td></tr>')
        body += f'<h3>Status per repo</h3><table><tr><th>Repo</th><th>Branch</th><th>Perubahan</th><th>Git</th></tr>{"".join(rows)}</table>'
    if report["checklist"]:
        items = []
        for check in report["checklist"]:
            mark, cls = CHECK[check["state"]]
            evidence = f'<div class="muted">{rich(check["evidence"])}</div>' if check["evidence"] else ""
            items.append(f'<li><span class="mark {cls}">{mark}</span><div><b>{rich(check["label"])}</b>{evidence}</div></li>')
        body += f'<h3>Kesiapan</h3><ul class="checks">{"".join(items)}</ul>'
    return section("ringkasan", "Ringkasan & kondisi saat ini", body, report["summary"])


def decisions_section(report):
    if not report["decisions"]:
        return section("keputusan", "Butuh keputusanmu", '<div class="callout ok">Tidak ada keputusan tertunda. Semua yang perlu diputuskan sudah dibahas di sesi.</div>')
    cards = []
    for index, item in enumerate(report["decisions"], 1):
        label, cls, card = DECISION[item["kind"]]
        options = "".join(f"<li>{rich(option)}</li>" for option in item["options"])
        options = f'<ul class="tight">{options}</ul>' if options else ""
        recommendation = f'<div class="rec"><b>Rekomendasi agent:</b> {rich(item["recommendation"])}</div>' if item["recommendation"] else ""
        cards.append(f'<div class="decision {card}">{tag(label, cls)}<h3>{index}. {rich(item["title"])}</h3><p>{rich(item["context"])}</p>{options}{recommendation}</div>')
    return section("keputusan", "Butuh keputusanmu", "".join(cards), "Hal-hal ini menunggu keputusanmu sebelum pekerjaan bisa dianggap final.")


def built_section(report):
    if not report["built"] and not report["key_decisions"]:
        return None
    cards = "".join(
        f'<div class="card"><h3>{rich(item["title"])}</h3><p>{rich(item["what"])}</p><div class="why"><b>Kenapa:</b> {rich(item["why"])}</div></div>'
        for item in report["built"]
    )
    body = f'<div class="grid g2">{cards}</div>' if cards else ""
    if report["key_decisions"]:
        rows = "".join(f'<tr><td>{rich(item["topic"])}</td><td>{rich(item["decision"])}</td><td>{rich(item["why"])}</td></tr>' for item in report["key_decisions"])
        body += f'<h3>Keputusan yang sudah diambil</h3><table><tr><th>Topik</th><th>Keputusan</th><th>Alasan</th></tr>{rows}</table>'
    return section("dibuat", "Apa yang dibuat & kenapa", body)


def architecture_section(report):
    item = report["architecture"]
    if not item or not item["mermaid"].strip():
        return None
    return section("arsitektur", "Arsitektur", legend(item) + diagram(item), "Komponen yang tersentuh di sesi ini dan aliran data di antaranya.")


def flows_section(report):
    flows = [flow for flow in report["flows"] if flow["after"]["mermaid"].strip()]
    if not flows:
        return None
    parts = [legend(*[d for flow in flows for d in (flow["before"], flow["after"])])]
    for flow in flows:
        if flow["before"] and flow["before"]["mermaid"].strip():
            parts.append(
                f'<h3>{rich(flow["name"])}</h3><div class="pair"><div><h4>Alur lama</h4>{diagram(flow["before"])}</div>'
                f'<div><h4>Alur baru</h4>{diagram(flow["after"])}</div></div>'
            )
        else:
            parts.append(f'<h3>{rich(flow["name"])}</h3>{diagram(flow["after"])}')
    return section("alur", "Alur", "".join(parts))


def lifecycle_section(report):
    items = [item for item in report["lifecycle"] if item["diagram"]["mermaid"].strip()]
    if not items:
        return None
    body = "".join(f'<h3>{rich(item["entity"])}</h3>{diagram(item["diagram"])}' for item in items)
    return section("siklus", "Siklus hidup", body, "Status yang bisa dilalui entitas ini dan apa yang memindahkannya.")


def implementation_section(groups):
    cards = []
    for group in groups:
        summary = "".join(f'<p>{rich(item["summary"])}</p>' for item in group["items"] if item["summary"])
        notes = "".join(f"<li>{rich(note)}</li>" for item in group["items"] for note in item["notes"])
        commits = "".join(f'<tr><td class="mono">{e(sha)}</td><td>{e(subject)}</td></tr>' for sha, subject in group["commits"])
        if not (summary or notes or commits):
            continue
        body = summary
        body += f'<table class="commits">{commits}</table>' if commits else ""
        body += f'<ul class="tight">{notes}</ul>' if notes else ""
        cards.append(f'<div class="card"><h3>{e(group["name"])}</h3>{body}</div>')
    if not cards:
        return None
    grid = "g3" if len(cards) > 1 else ""
    return section("implementasi", "Implementasi per repo", f'<div class="grid {grid}">{"".join(cards)}</div>')


def diff_html(entry):
    rows = []
    for line in entry["diff"]:
        if line.startswith(("diff --git", "index ", "--- ", "+++ ", "new file", "deleted file", "similarity", "old mode", "new mode")):
            cls = "m"
        elif line.startswith("@@"):
            cls = "h"
        elif line.startswith("+"):
            cls = "a"
        elif line.startswith("-"):
            cls = "d"
        else:
            cls = ""
        rows.append(f'<span class="{cls}">{e(line) or " "}</span>')
    if entry["truncated"]:
        rows.append(f'<span class="m">… diff dipotong setelah {DIFF_LINES} baris, lihat lengkapnya dengan git diff</span>')
    if not rows:
        rows.append('<span class="m">Tidak ada diff teks (file biner atau kosong).</span>')
    return f'<pre class="diff">{"".join(rows)}</pre>'


def files_section(groups):
    parts = []
    for group in groups:
        if not group["files"]:
            continue
        count, plus, minus = totals([group])
        rows = []
        for entry in group["files"]:
            label, cls = FILE_STATUS.get(entry["status"], ("diubah", "info"))
            delta = f'<span class="plus">+{e(entry["added"])}</span> <span class="minus">−{e(entry["deleted"])}</span>' if group["git"] else ""
            reason = rich(entry["reason"]) if entry["reason"] else '<span class="muted">–</span>'
            summary = f'<summary>{tag(label, cls)}<span class="path">{e(entry["path"])}</span><span class="delta">{delta}</span><span>{reason}</span></summary>'
            if group["git"]:
                rows.append(f'<details class="file">{summary}{diff_html(entry)}</details>')
            else:
                rows.append(f'<details class="file">{summary}<pre class="diff"><span class="m">File di luar repo git, diff tidak tersedia.</span></pre></details>')
        meta = f'{count} file · +{plus} / −{minus}' if group["git"] else f"{count} file"
        parts.append(f'<h3>{e(group["name"])} <span class="muted mono">{meta}</span></h3>{"".join(rows)}')
    if not parts:
        return None
    return section("file", "Daftar file berubah", "".join(parts), "Klik baris untuk melihat diff asli dari git.")


def review_section(report):
    review = report["code_review"]
    if not review["ran"]:
        return section("review", "Code review", '<div class="callout warn">Belum ada code review di sesi ini. Jalankan <code>/code-review</code> sebelum membuka PR.</div>')
    counts = {}
    for finding in review["findings"]:
        counts[finding["status"]] = counts.get(finding["status"], 0) + 1
    summary = " ".join(tag(f"{counts[key]} {FINDING[key][0].lower()}", FINDING[key][1]) for key in FINDING if key in counts)
    if not review["findings"]:
        body = '<div class="callout ok">Code review berjalan dan tidak menemukan masalah.</div>'
    else:
        rows = []
        for index, finding in enumerate(review["findings"], 1):
            label, cls = FINDING[finding["status"]]
            evidence = rich(finding["evidence"]) if finding["evidence"] else '<span class="muted">–</span>'
            rows.append(f'<tr><td>{index}</td><td>{rich(finding["title"])}</td><td>{tag(label, cls)}</td><td>{rich(finding["resolution"])}</td><td>{evidence}</td></tr>')
        body = f'<p>{summary}</p><table><tr><th>#</th><th>Temuan</th><th>Status</th><th>Perbaikan / alasan</th><th>Bukti</th></tr>{"".join(rows)}</table>'
    return section("review", "Code review", body, f"Sumber: {review['source']}" if review["source"] else "")


def tests_section(report):
    if not report["tests"]:
        return section("pengujian", "Pengujian otomatis", '<div class="callout warn">Tidak ada test, build, atau lint yang dijalankan di sesi ini, jadi belum ada bukti otomatis bahwa perubahan ini benar.</div>')
    rows = []
    for item in report["tests"]:
        label, cls = RESULT[item["result"]]
        command = f'<code>{e(item["command"])}</code>' if item["command"] else '<span class="muted">–</span>'
        detail = f'<div class="muted">{rich(item["detail"])}</div>' if item["detail"] else ""
        rows.append(f'<tr><td>{rich(item["layer"])}</td><td>{rich(item["scope"])}</td><td>{command}</td><td>{tag(label, cls)}{detail}</td></tr>')
    return section("pengujian", "Pengujian otomatis", f'<table><tr><th>Lapisan</th><th>Cakupan</th><th>Perintah</th><th>Hasil</th></tr>{"".join(rows)}</table>')


def embed(path, bases):
    candidates = [Path(path)] if os.path.isabs(path) else [Path(base) / path for base in bases]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        mime = mimetypes.guess_type(candidate.name)[0] or ""
        if not mime.startswith("image/"):
            return None, f"{path} bukan file gambar"
        if candidate.stat().st_size > SHOT_BYTES:
            return None, f"{path} terlalu besar untuk disematkan"
        return f"data:{mime};base64,{base64.b64encode(candidate.read_bytes()).decode()}", ""
    return None, f"screenshot {path} tidak ditemukan"


def e2e_section(report, bases):
    item = report["e2e"]
    if not item or not (item["scenarios"] or item["steps"]):
        return None
    body = ""
    if item["scenarios"]:
        rows = "".join(
            f'<tr><td>{rich(s["area"])}</td><td>{rich(s["name"])}'
            + (f' <span class="muted">· {rich(s["detail"])}</span>' if s["detail"] else "")
            + f'</td><td>{tag(*RESULT[s["result"]])}</td></tr>'
            for s in item["scenarios"]
        )
        body += f'<table><tr><th>Area</th><th>Skenario</th><th>Hasil</th></tr>{rows}</table>'
    if item["steps"]:
        steps = []
        for index, step in enumerate(item["steps"], 1):
            figure = ""
            if step["screenshot"]:
                source, problem = embed(step["screenshot"], bases)
                figure = (
                    f'<figure><img src="{source}" alt="{e(step["title"])}"><figcaption>{rich(step["title"])}</figcaption></figure>'
                    if source
                    else f'<div class="callout warn">{e(problem)}</div>'
                )
            fields = "".join(
                f"<dt>{label}</dt><dd>{rich(step[key])}</dd>"
                for key, label in (("action", "Aksi"), ("expected", "Diharapkan"), ("observed", "Hasil"))
                if step[key]
            )
            steps.append(
                f'<li><div class="step-head"><span>Langkah {index} · {rich(step["title"])}</span>{tag(*RESULT[step["result"]])}</div>'
                f'<dl class="step">{fields}</dl>{figure}</li>'
            )
        body += f'<h3>Langkah demi langkah</h3><ol class="steps">{"".join(steps)}</ol>'
    return section("e2e", "Uji end-to-end", body, item["environment"])


def tradeoff_section(report):
    if not report["tradeoffs"]:
        return section("tradeoff", "Known trade-off & risiko", '<div class="callout ok">Tidak ada trade-off atau risiko yang dicatat.</div>')
    rows = "".join(
        f'<tr><td>{tag(*LEVEL[item["level"]])}</td><td><b>{rich(item["item"])}</b></td><td>{rich(item["impact"])}</td></tr>'
        for item in report["tradeoffs"]
    )
    return section("tradeoff", "Known trade-off & risiko", f'<table><tr><th>Tingkat</th><th>Hal</th><th>Dampak / alasan</th></tr>{rows}</table>')


def scope_section(report):
    if not report["out_of_scope"]:
        return section("luar", "Di luar cakupan sesi", '<p class="muted">Tidak ada pekerjaan lanjutan yang tercatat.</p>')
    cards = []
    for item in report["out_of_scope"]:
        prompt = f'<div class="prompt"><button class="copy" type="button">Salin</button><pre>{e(item["prompt"])}</pre></div>' if item["prompt"] else ""
        cards.append(f'<div class="card"><h3>{rich(item["item"])}</h3><div class="why">{rich(item["why"])}</div>{prompt}</div>')
    return section("luar", "Di luar cakupan sesi", f'<div class="grid g2">{"".join(cards)}</div>', "Kandidat untuk sesi baru. Prompt di bawah bisa langsung disalin.")


def next_section(report):
    if not report["next_steps"]:
        return section("lanjut", "Langkah berikutnya untuk kamu", '<p class="muted">Tidak ada tindakan yang menunggu.</p>')
    items = "".join(f"<li>{rich(step)}</li>" for step in report["next_steps"])
    return section("lanjut", "Langkah berikutnya untuk kamu", f'<ol class="tight">{items}</ol>')


def page(title, body):
    template = common.TEMPLATE.read_text()
    return template.replace("{{TITLE}}", e(title)).replace("{{BODY}}", body)


def build(sid, report, groups, harness, moment, bases):
    sections = [
        summary_section(report, groups),
        decisions_section(report),
        built_section(report),
        architecture_section(report),
        flows_section(report),
        lifecycle_section(report),
        implementation_section(groups),
        files_section(groups),
        review_section(report),
        tests_section(report),
        e2e_section(report, bases),
        tradeoff_section(report),
        scope_section(report),
        next_section(report),
    ]
    sections = [item for item in sections if item]
    links = "".join(f'<a href="#{anchor}">{e(title)}</a>' for anchor, title, _ in sections)
    footer = f"<footer>Dibuat otomatis dari sesi {HARNESS[harness]} <code>{e(sid)}</code> · diperbarui {long_date(moment)} · berkas sementara di /tmp · <a href=\"index.html\">semua laporan</a></footer>"
    body = header(report, groups, harness, moment) + f'<nav><div class="wrap">{links}</div></nav><main>{"".join(markup for _, _, markup in sections)}{footer}</main>'
    return page(f"Laporan sesi: {report['title']}", body)


def point_latest(path):
    link = common.root() / "latest.html"
    temporary = link.with_name(f".latest.{os.getpid()}.tmp")
    os.symlink(path.name, temporary)
    os.replace(temporary, link)


def output_path(sid, meta, groups, cwd):
    known = meta.get("html")
    if known and common.is_under(known, common.root()):
        return Path(known)
    name = next((group["name"] for group in groups if group["git"]), Path(cwd).name)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "sesi"
    return common.root() / f"{slug}-{sid[:8]}.html"


def write_index():
    entries = []
    for path in common.state_dir().glob("*.json"):
        try:
            meta = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(meta, dict) and meta.get("html") and Path(meta["html"]).exists():
            entries.append(meta)
    entries.sort(key=lambda meta: meta.get("updated_at", 0), reverse=True)
    rows = []
    for meta in entries:
        label, cls = STATUS.get(meta.get("status"), ("?", "info"))
        decisions = meta.get("decisions", 0)
        pending = tag(f"{decisions} menunggu", "warn") if decisions else '<span class="muted">0</span>'
        moment = datetime.fromtimestamp(meta.get("updated_at", 0))
        rows.append(
            f'<tr><td class="mono">{moment:%d/%m %H:%M}</td><td><a href="{e(Path(meta["html"]).name)}">{e(meta.get("title", "?"))}</a></td>'
            f'<td>{e(", ".join(meta.get("repo_names", [])))}</td><td>{tag(label, cls)}</td><td>{pending}</td><td>{e(HARNESS.get(meta.get("harness"), "?"))}</td></tr>'
        )
    table = f'<table><tr><th>Diperbarui</th><th>Pekerjaan</th><th>Repo</th><th>Status</th><th>Keputusan</th><th>Harness</th></tr>{"".join(rows)}</table>'
    body = (
        f'<header><div class="wrap"><div class="eyebrow">{long_date(datetime.now())}</div><h1>Laporan sesi</h1>'
        f'<p>Semua sesi Claude Code dan Codex yang punya laporan, terbaru di atas.</p></div></header>'
        f'<main><section id="semua"><h2>Semua laporan</h2>{table}</section></main>'
    )
    common.write_atomic(common.root() / "index.html", page("Laporan sesi", body))


def browser(path):
    url = path.resolve().as_uri()
    return ["omarchy-launch-browser", url] if shutil.which("omarchy-launch-browser") else ["xdg-open", url]


def detach(command):
    try:
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


def notify(path, summary, body):
    if os.environ.get("SESSION_REPORT_NOTIFY", "1") == "0":
        return
    if shutil.which("omarchy-notification-send"):
        detach(["omarchy-notification-send", "--app-name", "Session Report", "-g", GLYPH, "-u", "normal", summary, body, "--exec", *browser(path)])
    elif shutil.which("notify-send"):
        detach(["notify-send", "-a", "Session Report", summary, body])


def resolve_session(value, cwd):
    if value != "auto":
        if not common.valid_sid(value):
            raise ReportError(f"invalid session id: {value!r}")
        return value
    root = common.repo_root(cwd) or os.path.normpath(cwd)
    journals = sorted(common.state_dir().glob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    for journal in journals:
        sid = journal.stem
        if any(common.is_under(event.get("path", ""), root) for event in common.events(sid) if event.get("path")):
            return sid
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(root).name).strip("-") or "sesi"
    return f"manual-{slug}"


def render(session, report_path, harness="claude", notify_user=True, cwd=None, open_now=False):
    cwd = cwd or os.getcwd()
    sid = resolve_session(session, cwd)
    report = load_report(report_path)
    if report["skip"]:
        return None
    meta = common.load_meta(sid)
    groups = collect(sid, report, meta, cwd)
    moment = datetime.now()
    bases = [cwd] + [group["root"] for group in groups if group["git"]]
    path = output_path(sid, meta, groups, cwd)
    common.write_atomic(path, build(sid, report, groups, harness, moment, bases))
    common.update_meta(
        sid,
        html=str(path),
        title=report["title"],
        status=report["status"],
        decisions=len(report["decisions"]),
        updated_at=time.time(),
        harness=harness,
        repo_names=[group["name"] for group in groups if group["git"]],
        report=str(report_path),
    )
    point_latest(path)
    write_index()
    if open_now:
        detach(browser(path))
    elif notify_user:
        names = ", ".join(group["name"] for group in groups if group["git"]) or "Laporan sesi"
        notify(path, f"{names}: {STATUS[report['status']][0]}", report["title"])
    return path


def main(argv):
    parser = argparse.ArgumentParser(description="Render a session-report report.json into HTML.")
    parser.add_argument("session", help="session id, or 'auto' to pick the newest tracked session for this directory")
    parser.add_argument("report", help="path to report.json")
    parser.add_argument("--harness", choices=sorted(HARNESS), default="claude")
    parser.add_argument("--no-notify", action="store_true")
    parser.add_argument("--open", action="store_true", help="open the report now instead of sending a notification")
    args = parser.parse_args(argv[1:])
    try:
        path = render(args.session, args.report, args.harness, not args.no_notify, open_now=args.open)
    except ReportError as error:
        print(f"report.json is not valid, fix these and render again:\n{error}", file=sys.stderr)
        return 2
    print("skip" if path is None else path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
