import argparse
import base64
import html
import json
import os
import re
import struct
import sys
import tempfile
import webbrowser
import zipfile
import zlib
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
STATUS = {'finished': ('Selesai', 'ok'), 'in_progress': ('Sebagian selesai', 'warn'), 'blocked': ('Ada kendala', 'bad')}
RESULT = {'observed': ('Tampilan diamati', 'info'), 'pass': ('Sesuai pemeriksaan', 'ok'), 'fail': ('Perlu perbaikan', 'bad')}
VERIFY = {'ui_only': 'Pemeriksaan tampilan', 'test_flow': 'Alur dengan data uji', 'end_to_end': 'Proses lengkap diperiksa', 'work_source': 'Bukti sumber pekerjaan'}
KINDS = {'pr': 'PR', 'commit': 'Commit', 'local': 'Pekerjaan lokal', 'investigation': 'Investigasi', 'other': 'Pekerjaan lain'}
CONTRIBUTION = {'created': 'Dibuat', 'worked_on': 'Dikerjakan', 'related': 'Sumber terkait'}


class ReportError(ValueError):
    pass


def validate_schema(value, schema, path='$'):
    if 'anyOf' in schema:
        if any(not validate_schema(value, option, path) for option in schema['anyOf']):
            return []
        return [f'{path}: bentuk data tidak sesuai.']
    types = {'object': dict, 'array': list, 'string': str, 'integer': int, 'boolean': bool, 'null': type(None)}
    expected = schema.get('type')
    if expected and (not isinstance(value, types[expected]) or expected == 'integer' and isinstance(value, bool)):
        return [f'{path}: perlu {expected}.']
    errors = []
    if 'enum' in schema and value not in schema['enum']:
        errors.append(f'{path}: nilai tidak dikenali.')
    if isinstance(value, str):
        if len(value.strip()) < schema.get('minLength', 0):
            errors.append(f'{path}: teks belum diisi.')
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            errors.append(f'{path}: format teks tidak sesuai.')
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0):
            errors.append(f'{path}: minimal {schema["minItems"]} item; screenshot wajib tersedia.')
        for index, item in enumerate(value):
            errors.extend(validate_schema(item, schema.get('items', {}), f'{path}[{index}]'))
    if isinstance(value, dict):
        properties = schema.get('properties', {})
        errors.extend(f'{path}.{key}: belum ada.' for key in schema.get('required', []) if key not in value)
        for key, item in value.items():
            if key in properties:
                errors.extend(validate_schema(item, properties[key], f'{path}.{key}'))
            elif schema.get('additionalProperties') is False:
                errors.append(f'{path}.{key}: bagian ini tidak termasuk format laporan.')
    return errors


def image_info(path):
    raw = path.read_bytes()
    if not raw or len(raw) > 16 * 1024 * 1024:
        raise ReportError(f'Screenshot kosong atau melebihi 16 MB: {path.name}')
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        offset, size, image_data, ended = 8, None, False, False
        while offset + 12 <= len(raw):
            length = int.from_bytes(raw[offset:offset + 4], 'big')
            kind = raw[offset + 4:offset + 8]
            chunk = raw[offset + 8:offset + 8 + length]
            if offset + length + 12 > len(raw):
                break
            checksum = int.from_bytes(raw[offset + 8 + length:offset + 12 + length], 'big')
            if zlib.crc32(kind + chunk) & 0xffffffff != checksum:
                raise ReportError(f'PNG rusak: {path.name}')
            if kind == b'IHDR' and length == 13:
                size = struct.unpack('>II', chunk[:8])
            image_data |= kind == b'IDAT' and bool(chunk)
            offset += length + 12
            if kind == b'IEND':
                ended = True
                break
        if not size or not all(size) or not image_data or not ended:
            raise ReportError(f'PNG belum lengkap: {path.name}')
        return 'image/png', raw
    if raw.startswith(b'\xff\xd8') and raw.endswith(b'\xff\xd9'):
        offset = 2
        while offset + 4 <= len(raw):
            if raw[offset] != 0xff:
                break
            while offset < len(raw) and raw[offset] == 0xff:
                offset += 1
            if offset >= len(raw):
                break
            marker = raw[offset]
            offset += 1
            if marker in (0xd8, 0xd9) or 0xd0 <= marker <= 0xd7:
                continue
            if offset + 2 > len(raw):
                break
            length = int.from_bytes(raw[offset:offset + 2], 'big')
            if length < 2 or offset + length > len(raw):
                break
            if marker in (0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf) and length >= 8:
                if all(struct.unpack('>HH', raw[offset + 3:offset + 7])):
                    return 'image/jpeg', raw
            offset += length
    if len(raw) >= 30 and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP' and int.from_bytes(raw[4:8], 'little') + 8 == len(raw):
        if raw[12:16] in (b'VP8 ', b'VP8L', b'VP8X'):
            return 'image/webp', raw
    raise ReportError(f'Perlu screenshot PNG, JPG, atau WebP yang valid: {path.name}')


def load_report(path):
    report = json.loads(path.read_text())
    schema = json.loads((ROOT / 'assets' / 'report.schema.json').read_text())
    errors = validate_schema(report, schema)
    if errors:
        raise ReportError('\n'.join(errors[:20]))
    date.fromisoformat(report['date'])
    ZoneInfo(report['timezone'])
    sources, refs = set(), {}
    for source in report['sources']:
        key = (source['kind'], source['repository'], source['reference'])
        if key in sources:
            raise ReportError('Sumber pekerjaan tercatat ganda.')
        sources.add(key)
        refs.setdefault(source['reference'], set()).add(source['repository'])
        if source['kind'] == 'commit' and not re.fullmatch(r'[a-fA-F0-9]{40}', source['reference']):
            raise ReportError('Sumber commit perlu SHA lengkap yang terbukti.')
        if source['kind'] == 'pr' and (not source['reference'].isdigit() or int(source['reference']) < 1):
            raise ReportError('Nomor PR belum valid.')
        url = source['url']
        if url and (urlsplit(url).scheme not in ('http', 'https') or not urlsplit(url).netloc):
            raise ReportError('Tautan sumber perlu HTTP/HTTPS yang valid.')
    images, ids, change_ids = {}, set(), set()
    for step in report['evidence']['steps']:
        if step['id'] in ids:
            raise ReportError('ID screenshot tercatat ganda.')
        ids.add(step['id'])
        raw_path = Path(step['screenshot']).expanduser()
        image_path = raw_path if raw_path.is_absolute() else path.parent / raw_path
        if not image_path.is_file():
            raise ReportError(f'Screenshot wajib belum tersedia untuk: {step["title"]}')
        mime, raw = image_info(image_path)
        images[step['id']] = (mime, raw, image_path)
    for change in report['changes']:
        if change['id'] in change_ids:
            raise ReportError('ID perubahan tercatat ganda.')
        change_ids.add(change['id'])
        if change['visual'] and not change['screenshot_ids']:
            raise ReportError(f'Perubahan UI memerlukan screenshot: {change["title"]}')
        if set(change['screenshot_ids']) - ids:
            raise ReportError(f'Rujukan screenshot tidak ditemukan: {change["title"]}')
        for ref in change['source_refs']:
            if ref in refs and len(refs[ref]) == 1:
                continue
            if not any(ref == f'{repo}#{reference}' for reference, repos in refs.items() for repo in repos):
                raise ReportError(f'Rujukan sumber belum ada atau ambigu: {ref}')
    return report, images


def escape(value):
    return html.escape(str(value), quote=True)


def rich(value):
    value = escape(value)
    value = re.sub(r'`([^`\n]+)`', r'<code>\1</code>', value)
    value = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', value)
    return value.replace('\n', '<br>')


def tag(label, cls='info'):
    return f'<span class="tag {cls}">{escape(label)}</span>'


def section(anchor, title, body, lead=''):
    intro = f'<p class="lead">{rich(lead)}</p>' if lead else ''
    return anchor, title, f'<section id="{anchor}"><h2>{escape(title)}</h2>{intro}{body}</section>'


def diagram(item):
    chart = f'<div class="diagram"><pre class="mermaid">{escape(item["mermaid"])}</pre></div>' if item['mermaid'].strip() else ''
    return f'<div class="diagram-block">{chart}<p class="explain">{rich(item["explanation"])}</p></div>'


def source_table(sources):
    if not sources:
        return '<p class="muted">Tidak ada PR atau commit yang tercatat pada cakupan laporan ini.</p>'
    rows = []
    for source in sources:
        reference = source['reference'][:8] if source['kind'] == 'commit' else source['reference']
        label = KINDS[source['kind']] + (f' #{reference}' if source['kind'] == 'pr' else f' {reference}')
        source_link = f'<a href="{escape(source["url"])}" target="_blank" rel="noopener noreferrer">{escape(label)}</a>' if source['url'] else escape(label)
        repo = f'<div class="muted">{rich(source["repository"])}</div>' if source['repository'] else ''
        state = rich(source['status']) + '<br>' + escape(CONTRIBUTION[source['contribution']])
        rows.append(f'<tr><td>{source_link}{repo}</td><td>{rich(source["title"])}</td><td>{state}</td></tr>')
    return '<table><thead><tr><th>Sumber</th><th>Pekerjaan</th><th>Status dan kontribusi</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table>'


def build(report, images):
    sources, changes = report['sources'], report['changes']
    stats = [(sum(s['kind'] == 'pr' for s in sources), 'PR tercatat'), (sum(s['kind'] == 'commit' for s in sources), 'commit tercatat'), (len(changes), 'perubahan atau pekerjaan'), (len(images), 'screenshot bukti')]
    cards = ''.join(f'<div class="stat"><b>{value}</b><span>{label}</span></div>' for value, label in stats)
    coverage = '<ul class="tight">' + ''.join(f'<li>{rich(item)}</li>' for item in report['coverage']) + '</ul>' if report['coverage'] else ''
    sections = [section('ringkasan', 'Ringkasan', f'<div class="grid g4">{cards}</div>{coverage}', report['summary'])]
    cards = []
    for change in changes:
        label, cls = STATUS[change['status']]
        before = f'<p><b>Sebelum:</b> {rich(change["before"])}</p>' if change['before'] else ''
        steps = '<ol class="tight">' + ''.join(f'<li>{rich(step)}</li>' for step in change['steps']) + '</ol>' if change['steps'] else ''
        pictures = '<p class="muted">Lihat bukti: ' + ', '.join(f'<a href="#bukti-{escape(sid)}">{escape(sid)}</a>' for sid in change['screenshot_ids']) + '</p>' if change['screenshot_ids'] else ''
        cards.append(f'<article class="card"><h3>{rich(change["title"])}</h3>{tag(label, cls)}{before}<p><b>Hasil sekarang:</b> {rich(change["after"])}</p>{steps}<p><b>Kenapa:</b> {rich(change["why"])}</p><div class="why"><b>Dampaknya:</b> {rich(change["impact"])}</div>{pictures}</article>')
    body = '<div class="grid g2">' + ''.join(cards) + '</div>' if cards else '<p>Tidak ada perubahan atau penambahan yang tercatat pada cakupan hari ini.</p>'
    body += '<h3>PR, commit, dan sumber pekerjaan</h3>' + source_table(sources)
    sections.append(section('dibuat', 'Apa yang dibuat & kenapa', body))
    sections.append(section('arsitektur', 'Arsitektur', diagram(report['architecture']), 'Hubungan orang, aplikasi, dan proses yang berkaitan dengan pekerjaan hari ini.'))
    lifecycle = []
    for item in report['lifecycle']:
        if item['before']:
            detail = f'<div class="pair"><div><h4>Sebelum</h4>{diagram(item["before"])}</div><div><h4>Sekarang</h4>{diagram(item["after"])}</div></div>'
        else:
            detail = diagram(item['after'])
        lifecycle.append(f'<h3>{rich(item["name"])}</h3>{detail}')
    sections.append(section('siklus', 'Siklus hidup', ''.join(lifecycle) or '<p>Tidak ada perubahan perjalanan status yang dicatat pada pekerjaan ini.</p>'))
    evidence = []
    for step in report['evidence']['steps']:
        label, cls = RESULT[step['result']]
        mime, raw, _ = images[step['id']]
        picture = f'data:{mime};base64,' + base64.b64encode(raw).decode()
        when = f' · {rich(step["captured_at"])}' if step['captured_at'] else ''
        evidence.append(f'<li id="bukti-{escape(step["id"])}"><div class="step-head"><span>{rich(step["title"])}</span>{tag(label, cls)}</div><p class="muted">{escape(VERIFY[step["verification"]])} · {rich(step["context"])}{when}</p><dl class="step"><dt>Langkah</dt><dd>{rich(step["action"])}</dd><dt>Yang diamati</dt><dd>{rich(step["observed"])}</dd></dl><figure><img src="{picture}" alt="{escape(step["title"])}" loading="eager"><figcaption>{rich(step["title"])}</figcaption></figure></li>')
    sections.append(section('e2e', 'Uji end-to-end', '<ol class="steps">' + ''.join(evidence) + '</ol>', report['evidence']['environment']))
    risks = []
    for risk in report['risks']:
        cls = {'perhatian': 'bad', 'sedang': 'warn', 'rendah': 'info'}[risk['level']]
        follow = f'<p><b>Tindak lanjut:</b> {rich(risk["follow_up"])}</p>' if risk['follow_up'] else ''
        risks.append(f'<article class="card">{tag(risk["level"], cls)}<h3>{rich(risk["title"])}</h3><p>{rich(risk["impact"])}</p>{follow}</article>')
    sections.append(section('risiko', 'Known trade-off & risiko', '<div class="grid g2">' + ''.join(risks) + '</div>' if risks else '<p>Tidak ada risiko tambahan yang tercatat pada cakupan laporan ini.</p>'))
    label, cls = STATUS[report['status']]
    updated = datetime.now(ZoneInfo(report['timezone'])).strftime('%d %B %Y · %H:%M')
    header = f'<header><div class="wrap"><div class="eyebrow">Laporan harian · {escape(report["date"])} · {escape(report["timezone"])}</div><h1>{escape(report["title"])}</h1><div class="verdict"><span class="status {cls}">{escape(label)}</span><span>{rich(report["status_note"])}</span></div></div></header>'
    links = ''.join(f'<a href="#{anchor}">{escape(title)}</a>' for anchor, title, _ in sections)
    body = header + f'<nav><div class="wrap">{links}</div></nav><main>' + ''.join(markup for _, _, markup in sections) + f'<footer>Laporan pekerjaan {escape(report["date"])} · {escape(report["scope"])} · Diperbarui {escape(updated)} ({escape(report["timezone"])})</footer></main>'
    template = (ROOT / 'assets' / 'template.html').read_text()
    has_diagrams = any(item['mermaid'].strip() for item in [report['architecture']] + [d for item in report['lifecycle'] for d in (item['before'], item['after']) if d])
    bundle = (ROOT / 'assets' / 'vendor' / 'mermaid-11.12.0.min.js').read_text() if has_diagrams else ''
    script = '<script>' + re.sub(r'</script', r'<\\/script', bundle, flags=re.I) + '</script>' if bundle else ''
    return template.replace('{{TITLE}}', escape(report['title'])).replace('{{BODY}}', body).replace('{{MERMAID}}', script)


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(data)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def archive_images(path, report, images):
    fd, name = tempfile.mkstemp(prefix='.screenshots.', suffix='.zip', dir=path.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(name, 'w', zipfile.ZIP_DEFLATED) as archive:
            captions = ['Screenshot laporan harian ' + report['date'], report['evidence']['environment'], '']
            for index, step in enumerate(report['evidence']['steps'], 1):
                mime, raw, _ = images[step['id']]
                extension = {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}[mime]
                filename = f'{index:02d}-screenshot.{extension}'
                archive.writestr(filename, raw)
                captions.append(f'{filename} — {step["title"]}\n{step["context"]}\n{step["observed"]}\n')
            archive.writestr('keterangan.txt', '\n'.join(captions))
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description='Render enam bagian laporan harian dengan screenshot wajib.')
    parser.add_argument('data', type=Path)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    try:
        data_path = args.data.expanduser().resolve()
        report, images = load_report(data_path)
        if args.check:
            print(f'Valid: {len(report["changes"])} pekerjaan, {len(images)} screenshot.')
            return 0
        output = data_path.with_name('report.html')
        markup = build(report, images)
        archive_images(data_path.with_name('report-screenshots.zip'), report, images)
        atomic_write(output, markup)
        if args.open:
            webbrowser.open(output.as_uri())
        print(str(output))
        return 0
    except (ReportError, ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        print(f'Laporan belum selesai: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
