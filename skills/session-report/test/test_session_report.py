import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / 'scripts'))
import install


class ManualReportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sr-manual-test.')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'backend'
        self.repo.mkdir()
        self.reports = self.base / 'reports'
        self.env = {**os.environ, 'SESSION_REPORT_DIR': str(self.reports), 'CODEX_THREAD_ID': 'manual-test-session'}
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'test')
        self.git('config', 'user.email', 'test@example.com')
        (self.repo / 'café.txt').write_text('old\n-- old comment\n')
        self.git('add', 'café.txt')
        self.git('commit', '-qm', 'feat(test): add base')
        self.data = json.loads((SKILL / 'test/fixtures/report.json').read_text())
        self.data.update(architecture=None, flows=[], lifecycle=[], e2e=None, code_review={'ran': False, 'source': '', 'findings': []})
        self.data['repos'] = [{'path': str(self.repo), 'summary': 'implementation', 'notes': [], 'files': [{'path': 'café.txt', 'reason': 'session change'}]}]
        self.source = self.base / 'report.json'

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True).strip()

    def run_script(self, name, *args, env=None):
        return subprocess.run([sys.executable, str(SKILL / 'scripts' / name), *args], cwd=self.repo, env=env or self.env, capture_output=True, text=True)

    def render(self, sid='manual-test-session'):
        self.source.write_text(json.dumps(self.data))
        result = self.run_script('render.py', sid, str(self.source), '--harness', 'codex')
        self.assertEqual(result.returncode, 0, result.stderr)
        return Path(result.stdout.strip())

    def test_repeated_call_updates_existing_html_and_prepare_finds_data(self):
        (self.repo / 'café.txt').write_text('new\n')
        first = self.render()
        self.data['title'] = 'Updated report title'
        second = self.render()
        self.assertEqual(first, second)
        self.assertIn('Updated report title', second.read_text())
        self.assertEqual(len(list(self.reports.glob('backend-*.html'))), 1)
        result = self.run_script('prepare.py', 'auto', '--harness', 'codex')
        self.assertEqual(result.returncode, 0, result.stderr)
        prepared = json.loads(result.stdout)
        self.assertEqual(prepared['html'], str(first))
        self.assertIsNone(prepared['previous_data'])
        self.source = Path(prepared['data_path'])
        self.render()
        prepared = json.loads(self.run_script('prepare.py', 'auto', '--harness', 'codex').stdout)
        self.assertEqual(prepared['previous_data'], str(self.source))
        self.assertEqual(os.readlink(self.reports / 'latest.html'), first.name)

    def test_existing_legacy_html_path_is_reused(self):
        state = self.reports / '.state'
        state.mkdir(parents=True)
        old = self.reports / 'session-report-old.html'
        old.write_text('old report')
        (state / 'manual-test-session.json').write_text(json.dumps({'html': str(old)}))
        self.assertEqual(self.render(), old)
        self.assertIn('<html', old.read_text())

    def test_review_absent_is_hidden(self):
        page = self.render().read_text()
        self.assertNotIn('<section id="review">', page)
        self.assertNotIn('belum ada code review', page.lower())
        self.assertNotIn('temuan review diperbaiki', page)

    def test_review_results_remain_visible(self):
        self.data['code_review'] = json.loads((SKILL / 'test/fixtures/report.json').read_text())['code_review']
        page = self.render().read_text()
        self.assertIn('<section id="review">', page)
        self.assertIn('temuan review diperbaiki', page)

    def test_committed_session_patch_is_explicit_and_upstream_excluded(self):
        (self.repo / 'café.txt').write_text('session content\n')
        self.git('commit', '-qam', 'fix(test): change session file')
        session_commit = self.git('rev-parse', 'HEAD')
        (self.repo / 'other.txt').write_text('upstream content')
        self.git('add', 'other.txt')
        self.git('commit', '-qm', 'feat(other): add unrelated upstream file')
        self.data['repos'][0]['commits'] = [session_commit]
        page = self.render().read_text()
        self.assertIn('fix(test): change session file', page)
        self.assertNotIn('feat(other): add unrelated upstream file', page)
        self.assertNotIn('other.txt', page)
        self.assertIn('+session content', page)

    def test_unicode_path_and_sql_comment_diff(self):
        (self.repo / 'café.txt').write_text('new\n')
        page = self.render().read_text()
        self.assertIn('café.txt', page)
        self.assertIn('<span class="d">--- old comment</span>', page)

    def test_missing_identity_fails_without_selecting_other_report(self):
        self.render()
        env = dict(self.env)
        env.pop('CODEX_THREAD_ID')
        result = self.run_script('prepare.py', 'auto', '--harness', 'codex', env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn('session id unavailable', result.stderr)

    def test_separate_sessions_keep_separate_reports(self):
        first = self.render()
        second = self.render('other-session')
        self.assertNotEqual(first, second)
        self.assertTrue(first.exists())

    def test_invalid_schema_and_session_errors_differ(self):
        self.source.write_text('{}')
        result = self.run_script('render.py', 'manual-test-session', str(self.source))
        self.assertEqual(result.returncode, 2)
        result = self.run_script('render.py', '../bad', str(self.source))
        self.assertEqual(result.returncode, 1)

    def test_invalid_commit_hash_is_rejected(self):
        self.data['repos'][0]['commits'] = ['HEAD']
        self.source.write_text(json.dumps(self.data))
        result = self.run_script('render.py', 'manual-test-session', str(self.source))
        self.assertEqual(result.returncode, 2)
        self.assertIn('commits[0]', result.stderr)

    def test_diagrams_and_api_e2e_still_render(self):
        fixture = json.loads((SKILL / 'test/fixtures/report.json').read_text())
        for field in ('architecture', 'flows', 'lifecycle'):
            self.data[field] = fixture[field]
        self.data['e2e'] = {**fixture['e2e'], 'steps': [step for step in fixture['e2e']['steps'] if not step['screenshot']]}
        page = self.render().read_text()
        for anchor in ('arsitektur', 'alur', 'siklus', 'e2e'):
            self.assertIn(f'<section id="{anchor}">', page)
        self.assertIn('Alur lama', page)
        self.assertIn('class="mermaid"', page)
        self.assertNotIn('src="data:image/', page)

    def test_private_permissions_and_offline_bundle(self):
        path = self.render()
        self.assertEqual(self.reports.stat().st_mode & 0o777, 0o700)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        page = path.read_text()
        self.assertIn('connect-src', page)
        self.assertNotIn('src="https://cdn.jsdelivr.net', page)

    def test_migration_preserves_unrelated_hooks_and_first_backup(self):
        path = self.base / 'settings.json'
        own = {'type': 'command', 'command': f'/usr/bin/python3 {SKILL}/scripts/gate.py --harness claude', 'asyncRewake': True}
        other = {'type': 'command', 'command': 'echo other'}
        original = {'hooks': {'Stop': [{'hooks': [own, other]}], 'PreToolUse': [{'hooks': [{'type': 'command', 'command': f'python3 {SKILL}/scripts/track.py'}]}]}, 'unrelated': 42}
        path.write_text(json.dumps(original))
        self.assertTrue(install.migrate(path))
        migrated = json.loads(path.read_text())
        self.assertEqual(migrated['hooks'], {'Stop': [{'hooks': [other]}]})
        self.assertEqual(migrated['unrelated'], 42)
        self.assertFalse(install.migrate(path))
        self.assertEqual(json.loads(path.with_name(path.name + '.bak-session-report-manual').read_text()), original)

    def test_installation_links_both_harnesses_and_is_idempotent(self):
        home = self.base / 'new user'
        env = {**self.env, 'HOME': str(home)}
        first = self.run_script('install.py', env=env)
        self.assertEqual(first.returncode, 0, first.stderr)
        for relative in ('.agents/skills/session-report', '.claude/skills/session-report'):
            self.assertEqual((home / relative).resolve(), SKILL)
        second = self.run_script('install.py', env=env)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn('skill already available', second.stdout)
        self.assertFalse((home / '.codex/hooks.json').exists())
        self.assertFalse((home / '.claude/settings.json').exists())

    def test_installation_preserves_conflicting_skill_directory(self):
        destination = self.base / 'existing-skill'
        destination.mkdir()
        marker = destination / 'keep.txt'
        marker.write_text('existing content')
        with self.assertRaises(ValueError):
            install.link_skill(destination)
        self.assertEqual(marker.read_text(), 'existing content')

    def test_cached_legacy_hook_entrypoints_have_no_side_effects(self):
        for name in ('track.py', 'gate.py'):
            result = self.run_script(name)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')
        self.assertFalse(self.reports.exists())


if __name__ == '__main__':
    unittest.main()
