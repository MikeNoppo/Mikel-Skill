import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('collection_install', ROOT / 'scripts/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mikel-skill-install-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
    def test_both_harnesses_find_both_skills(self):
        installer.install(self.home)
        for base in ('.agents/skills', '.claude/skills'):
            for name in installer.NAMES:
                link = self.home / base / name
                self.assertTrue(link.is_symlink())
                self.assertEqual(link.resolve(), ROOT / 'skills' / name)
    def test_repeated_install_is_idempotent(self):
        installer.install(self.home)
        self.assertEqual(installer.install(self.home), installer.install(self.home))
    def test_conflict_does_not_leave_partial_installation(self):
        conflict = self.home / '.claude/skills/day-report'
        conflict.mkdir(parents=True)
        marker = conflict / 'keep.txt';marker.write_text('keep')
        with self.assertRaises(ValueError):installer.install(self.home)
        self.assertEqual(marker.read_text(),'keep')
        self.assertFalse((self.home / '.agents/skills/session-report').exists())


if __name__ == '__main__':
    unittest.main()
