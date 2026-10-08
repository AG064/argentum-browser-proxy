import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from test_web_boundaries import load_app


class CloudflareHelperTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='proxy-helper-')
        self.root = Path(self.directory.name).resolve()
        self.install = self.root / 'trusted helper with spaces'
        self.install.mkdir()
        self.untrusted = self.root / 'untrusted caller'
        self.untrusted.mkdir()
        self.source = Path(__file__).resolve().parents[1]
        self.helper = self.install / 'cloudflare.sh'
        self.helper.write_bytes((self.source / 'cloudflare.sh').read_bytes().replace(b'\r\n', b'\n'))
        (self.untrusted / 'cloudflare.js').write_text('throw new Error("Decoy executed");', encoding='utf-8')
        self.bash = str(Path('C:/Program Files/Git/bin/bash.exe')) if os.name == 'nt' and Path('C:/Program Files/Git/bin/bash.exe').is_file() else shutil.which('bash')

    def tearDown(self):
        self.assertTrue(self.root.name.startswith('proxy-helper-'))
        self.directory.cleanup()

    def run_helper(self, url):
        if not self.bash or not shutil.which('node'):
            self.skipTest('Bash and Node are required for the executable-selection check')
        return subprocess.run([self.bash, str(self.helper), url], cwd=self.untrusted, capture_output=True, text=True, encoding='utf-8', timeout=15)

    def test_helper_selects_its_adjacent_script_and_keeps_url_as_one_argument(self):
        (self.install / 'cloudflare.js').write_text('console.log(JSON.stringify({path:process.argv[1],url:process.argv[2],cwd:process.cwd()}));', encoding='utf-8')
        url = 'https://site.test/?x=$(printf unsafe)&quoted="value"'
        run = self.run_helper(url)
        self.assertEqual(run.returncode, 0, run.stderr)
        data = json.loads(run.stdout)
        self.assertEqual(Path(data['path']).resolve(), self.install / 'cloudflare.js')
        self.assertEqual(Path(data['cwd']).resolve(), self.install)
        self.assertEqual(data['url'], url)

    def test_missing_adjacent_script_does_not_select_the_caller_decoy(self):
        run = self.run_helper('https://site.test/')
        self.assertNotEqual(run.returncode, 0)
        self.assertNotIn('Decoy executed', run.stderr)

    def test_actual_javascript_resolves_the_adjacent_esm_dependency(self):
        shutil.copyfile(self.source / 'cloudflare.js', self.install / 'cloudflare.js')
        (self.install / 'package.json').write_text('{"type":"module"}', encoding='utf-8')
        package = self.install / 'node_modules/playwright'
        package.mkdir(parents=True)
        (package / 'package.json').write_text('{"type":"module","exports":"./index.js"}', encoding='utf-8')
        (package / 'index.js').write_text('export const chromium={launch:async()=>({newContext:async()=>({newPage:async()=>({goto:async()=>{},waitForTimeout:async()=>{},content:async()=>"fixture",title:async()=>"fixture"}),cookies:async()=>[{name:"fixture",value:process.argv[1]}]}),close:async()=>{}})};', encoding='utf-8')
        run = self.run_helper('https://site.test/')
        self.assertEqual(run.returncode, 0, run.stderr)
        data = json.loads(run.stdout)
        self.assertTrue(data['success'])
        self.assertEqual(Path(data['cookies'][0]['value']).resolve(), self.install / 'cloudflare.js')

    def test_proxy_caller_selects_the_installed_repository_helper(self):
        module = load_app('proxy.py', self.root)
        result = type('Result', (), {'returncode': 0, 'stdout': '{"success":true,"cookies":[],"user_agent":"fixture"}'})()
        with patch.object(module.subprocess, 'run', return_value=result) as call:
            module.bypass_cloudflare('https://site.test/')
        self.assertEqual(Path(call.call_args.args[0][0]).resolve(), self.source / 'cloudflare.sh')
        self.assertEqual(call.call_args.args[0][1], 'https://site.test/')
        self.assertEqual(Path(call.call_args.kwargs['cwd']).resolve(), self.source)


if __name__ == '__main__':
    unittest.main()
