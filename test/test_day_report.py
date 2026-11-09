import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile
import struct
import zlib
import unittest
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--skill',type=Path,default=Path(__file__).resolve().parent.parent/'skills/day-report')
parser.add_argument('--fixture',type=Path,default=Path(__file__).resolve().parent/'fixtures/day-report.json')
args,remaining=parser.parse_known_args()
SKILL=args.skill.resolve()
BASE=json.loads(args.fixture.read_text())


class SectionParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sections=[]
    def handle_starttag(self,tag,attrs):
        if tag=='section':
            self.sections.append(dict(attrs).get('id'))


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory(prefix='day-report-test-')
        self.root=Path(self.directory.name)
        self.data=self.root/'report.json'
        self.report=copy.deepcopy(BASE)
        if self.report['evidence']['steps'][0]['screenshot']=='fixture.png':
            def chunk(kind,data):
                return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
            pixels=b''.join(b'\x00'+b'\xff\xff\xff'*16 for _ in range(16))
            raw=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',16,16,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b'')
            image=self.root/'fixture.png';image.write_bytes(raw)
            self.report['evidence']['steps'][0]['screenshot']=str(image)
    def tearDown(self):
        self.directory.cleanup()
    def run_report(self,check=False):
        self.data.write_text(json.dumps(self.report))
        command=[sys.executable,str(SKILL/'scripts/render.py'),str(self.data)]
        if check:command.append('--check')
        return subprocess.run(command,capture_output=True,text=True)
    def test_valid_output_is_six_sections_with_embedded_image(self):
        result=self.run_report()
        self.assertEqual(result.returncode,0,result.stderr)
        markup=(self.root/'report.html').read_text()
        parser=SectionParser();parser.feed(markup)
        self.assertEqual(parser.sections,['ringkasan','dibuat','arsitektur','siklus','e2e','risiko'])
        self.assertIn('data:image/png;base64,',markup)
        self.assertNotIn('Daftar file berubah',markup)
        self.assertNotIn('<script src=',markup)
        self.assertTrue((self.root/'report-screenshots.zip').is_file())
    def test_missing_screenshot_preserves_existing_final(self):
        previous=self.root/'report.html';previous.write_text('previous valid final')
        self.report['evidence']['steps'][0]['screenshot']='missing.png'
        result=self.run_report()
        self.assertEqual(result.returncode,2)
        self.assertEqual(previous.read_text(),'previous valid final')
        self.assertFalse((self.root/'report-screenshots.zip').exists())
    def test_no_screenshots_cannot_finish(self):
        self.report['evidence']['steps']=[]
        self.assertEqual(self.run_report().returncode,2)
        self.assertFalse((self.root/'report.html').exists())
    def test_visual_change_requires_its_screenshot(self):
        self.report['changes'][0]['screenshot_ids']=[]
        result=self.run_report()
        self.assertEqual(result.returncode,2)
        self.assertIn('Perubahan UI',result.stderr)
    def test_placeholder_file_is_rejected(self):
        image=self.root/'placeholder.png';image.write_text('screenshot pending')
        self.report['evidence']['steps'][0]['screenshot']=str(image)
        self.assertEqual(self.run_report().returncode,2)
    def test_corrupt_png_is_rejected(self):
        raw=bytearray(Path(self.report['evidence']['steps'][0]['screenshot']).read_bytes())
        raw[30]^=1
        image=self.root/'corrupt.png';image.write_bytes(raw)
        self.report['evidence']['steps'][0]['screenshot']=str(image)
        self.assertEqual(self.run_report().returncode,2)
    def test_unknown_screenshot_id_is_rejected(self):
        self.report['changes'][0]['screenshot_ids']=['unknown']
        self.assertEqual(self.run_report().returncode,2)
    def test_short_commit_id_is_rejected(self):
        source=copy.deepcopy(self.report['sources'][0])
        source.update(kind='commit',reference='abcdef12')
        self.report['sources'].append(source)
        self.assertEqual(self.run_report().returncode,2)
    def test_duplicate_sources_are_rejected(self):
        self.report['sources'].append(copy.deepcopy(self.report['sources'][0]))
        self.assertEqual(self.run_report().returncode,2)
    def test_same_pr_number_needs_repository_reference(self):
        source=copy.deepcopy(self.report['sources'][0]);source['repository']='different-repo'
        self.report['sources'].append(source)
        self.assertEqual(self.run_report(check=True).returncode,2)
        self.report['changes'][0]['source_refs']=[self.report['sources'][0]['repository']+'#'+self.report['sources'][0]['reference']]
        self.assertEqual(self.run_report(check=True).returncode,0)
    def test_script_url_is_rejected(self):
        self.report['sources'][0]['url']='javascript:alert(1)'
        self.assertEqual(self.run_report().returncode,2)
    def test_user_text_is_escaped(self):
        self.report['title']='<img src=x onerror=alert(1)>'
        self.assertEqual(self.run_report().returncode,0)
        markup=(self.root/'report.html').read_text()
        self.assertNotIn('<img src=x onerror=alert(1)>',markup)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;',markup)
    def prepare(self,day,zone):
        result=subprocess.run([sys.executable,str(SKILL/'scripts/prepare.py'),'--date',day,'--timezone',zone,'--scope','test','--root',str(self.root)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        return json.loads(result.stdout)
    def test_local_day_boundaries_are_not_utc_dates(self):
        state=self.prepare('2026-11-09','Asia/Jakarta')
        self.assertEqual(state['utc_start_inclusive'],'2026-11-08T17:00:00+00:00')
        self.assertEqual(state['utc_end_exclusive'],'2026-11-09T17:00:00+00:00')
    def test_dst_day_can_span_twenty_five_hours(self):
        state=self.prepare('2026-10-25','Europe/London')
        start=datetime.fromisoformat(state['utc_start_inclusive'])
        end=datetime.fromisoformat(state['utc_end_exclusive'])
        self.assertEqual((end-start).total_seconds(),25*3600)
    def test_prepare_reuses_only_same_day_and_scope(self):
        state=self.prepare('2026-11-09','Asia/Jakarta')
        Path(state['data_path']).write_text('{}')
        again=self.prepare('2026-11-09','Asia/Jakarta')
        other=self.prepare('2026-11-10','Asia/Jakarta')
        self.assertEqual(again['previous_data'],state['data_path'])
        self.assertIsNone(other['previous_data'])


if __name__=='__main__':
    unittest.main(argv=[sys.argv[0],*remaining])
