import ast
import concurrent.futures
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import types
import unittest
from fixture_guards import unit_guards
from unittest.mock import patch
import resource_limits as limits


class JobLimitTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(unit_guards())
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.outputs = self.root / 'outputs'
        self.outputs.mkdir()
        self.budget = limits.JobBudget(self.root / 'state', interval=60)
        self.real_popen = subprocess.Popen
        self.processes = []
        self.arguments = []

    def tearDown(self):
        self.budget.close()
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
        self.temp.cleanup()

    def fake_launch(self, arguments, **kwargs):
        self.arguments.append(arguments)
        process = self.real_popen([sys.executable, '-c',
            'import sys,time;sys.stderr.buffer.write(b"x"*65536);sys.stderr.flush();time.sleep(60)'], **kwargs)
        self.processes.append(process)
        return process

    def start(self, streams, key='test', **kwargs):
        directory = self.outputs / (key + str(len(self.processes)))
        command = ['ffmpeg', '-re', '-i', 'fixture', '-c:v', 'libx264', str(directory / 'playlist.m3u8')]
        with patch.object(limits.subprocess, 'Popen', side_effect=self.fake_launch):
            process = self.budget.start(command, streams, key, directory, self.outputs, **kwargs)
        return process, directory

    def module(self, filename):
        repo = Path(__file__).resolve().parents[1]
        tree = ast.parse((repo / filename).read_text(encoding='utf-8'))
        directory = self.outputs / filename.replace('.', '-')
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(n, ast.Name) and n.id == 'STREAM_DIR' for n in node.targets):
                node.value = ast.Constant(str(directory))
        module = types.ModuleType('limits_' + filename.replace('.', '_'))
        module.__file__ = str(repo / filename)
        with patch.object(limits, 'JOB_BUDGET', self.budget):
            exec(compile(ast.fix_missing_locations(tree), module.__file__, 'exec'), module.__dict__)
        module.time = types.SimpleNamespace(time=time.time, sleep=lambda _: None)
        return module

    def test_atomic_admission_and_independent_process_accounting(self):
        def reserve(_):
            try:
                return self.budget.reserve()
            except limits.JobCapacityError:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            leases = [x for x in pool.map(reserve, range(8)) if x]
        self.assertEqual(len(leases), 2)
        environment = dict(os.environ, ARGENTUM_PROXY_JOB_STATE_DIR=str(self.root / 'state'))
        command = [sys.executable, '-c', 'from resource_limits import JOB_BUDGET; JOB_BUDGET.reserve()']
        rejected = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=environment,
                                  capture_output=True, text=True, timeout=10)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn('JobCapacityError', rejected.stderr)
        for lease in leases:
            self.budget.release(lease)
        accepted = subprocess.run(command[:-1] + ['from resource_limits import JOB_BUDGET; print(JOB_BUDGET.reserve())'],
            cwd=Path(__file__).resolve().parents[1], env=environment, capture_output=True, text=True, timeout=10)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.budget.release(accepted.stdout.strip())

    def test_all_five_routes_keep_response_contracts_and_stop_outputs(self):
        cases = [('proxy.py', '/watch', '/stream/stop/'),
                 ('proxy.py', '/transcode', '/hls/stop/'),
                 ('browser_app.py', '/browser/stream/start', '/browser/stream/stop/'),
                 ('stream_proxy.py', '/stream', '/stop/'),
                 ('stream_proxy.py', '/proxy', '/stop/')]
        for filename, route, stop in cases:
            with self.subTest(route=route):
                module = self.module(filename)
                with patch.object(limits.subprocess, 'Popen', side_effect=self.fake_launch):
                    response = module.app.test_client().get(route + '?url=https://fixture.invalid/video')
                self.assertIn(response.status_code, [200, 302], response.data)
                if route == '/watch':
                    key = re.search(rb'/hls/([a-f0-9]+)/playlist', response.data).group(1).decode()
                    self.assertIn(b'<source', response.data)
                elif route == '/proxy':
                    key = 'direct'
                    self.assertEqual(response.headers['Location'], '/hls/direct/playlist.m3u8')
                else:
                    key = response.json['stream_id']
                    self.assertEqual(response.json['status'], 'started')
                    if route == '/transcode':
                        self.assertIn('hls_url', response.json)
                        self.assertIn('video_url', response.json)
                    if route == '/stream':
                        self.assertIn('playlist_url', response.json)
                info = module.STREAMS[key]
                output = Path(info['segment_dir'])
                (output / 'playlist.m3u8').write_text('#EXTM3U\nsegment_001.ts\n')
                (output / 'segment_001.ts').write_bytes(b'fixture media')
                prefix = '/browser/hls/' if filename == 'browser_app.py' else '/hls/'
                playlist = module.app.test_client().get(prefix + key + '/playlist.m3u8')
                self.assertEqual(playlist.status_code, 200)
                self.assertEqual(playlist.headers['Cache-Control'], 'no-cache')
                segment = module.app.test_client().get(prefix + key + '/segment_001.ts')
                self.assertEqual(segment.data, b'fixture media')
                segment.close()
                partial = module.app.test_client().get(prefix + key + '/segment_001.ts',
                                                      headers={'Range': 'bytes=0-3'})
                self.assertEqual(partial.status_code, 206)
                self.assertEqual(partial.data, b'fixt')
                self.assertEqual(partial.headers['Content-Length'], '4')
                partial.close()
                self.assertEqual(module.app.test_client().get(stop + key).status_code, 200)
                self.assertIsNotNone(info['process'].poll())
                self.assertFalse(output.exists())
                self.assertNotIn(key, module.STREAMS)
        for command in self.arguments:
            self.assertEqual(command.count('-threads'), 2)
            self.assertIn('-rw_timeout', command)
            self.assertIn('-nostdin', command)

    def test_capacity_rejects_browser_prework_and_other_servers(self):
        proxy = self.module('proxy.py')
        secondary = self.module('stream_proxy.py')
        with patch.object(limits.subprocess, 'Popen', side_effect=self.fake_launch):
            first = proxy.app.test_client().get('/transcode?url=https://fixture.invalid/one')
            second = secondary.app.test_client().get('/stream?url=https://fixture.invalid/two')
            before = len(self.processes)
            proxy.PLAYWRIGHT_AVAILABLE = True
            proxy.sync_playwright = unittest.mock.Mock(side_effect=AssertionError('Browser must not launch'))
            denied = proxy.app.test_client().get('/transcode?page_url=https://fixture.invalid/page')
            self.assertEqual(denied.status_code, 503)
            self.assertEqual(denied.headers['Retry-After'], '5')
            self.assertEqual(proxy.app.test_client().get('/extract?url=https://fixture.invalid/page').status_code, 503)
            self.assertEqual(secondary.app.test_client().get('/proxy?url=https://fixture.invalid/three').status_code, 503)
            self.assertEqual(len(self.processes), before)
            proxy.sync_playwright.assert_not_called()
        proxy.app.test_client().get('/hls/stop/' + first.json['stream_id'])
        secondary.app.test_client().get('/stop/' + second.json['stream_id'])

    def test_failed_launch_and_existing_directory_preserve_ownership(self):
        directory = self.outputs / 'failed'
        command = ['ffmpeg', '-i', 'fixture', str(directory / 'playlist.m3u8')]
        with patch.object(limits.subprocess, 'Popen', side_effect=OSError('fixture launch failure')):
            with self.assertRaises(OSError):
                self.budget.start(command, {}, 'failed', directory, self.outputs)
        self.assertFalse(directory.exists())
        directory.mkdir()
        (directory / 'owned-by-other-job').write_bytes(b'preserve')
        with self.assertRaises(FileExistsError):
            self.budget.start(command, {}, 'collision', directory, self.outputs)
        self.assertTrue((directory / 'owned-by-other-job').exists())
        leases = [self.budget.reserve(), self.budget.reserve()]
        for lease in leases:
            self.budget.release(lease)

    def test_stderr_is_drained_and_retained_diagnostics_are_bounded(self):
        streams = {}
        process, _ = self.start(streams)
        deadline = time.monotonic() + 3
        while process.bytes == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIsNone(process.poll())
        self.assertGreater(len(process.stderr.read()), 0)
        self.assertLessEqual(len(process.stderr.read()), 4096)
        self.budget.stop(streams, 'test')
        self.assertIsNotNone(process.poll())

    def test_failed_cleanup_keeps_ownership_and_retries(self):
        streams = {}
        directory = self.outputs / 'failed-cleanup'
        command = ['ffmpeg', '-i', 'fixture', str(directory / 'playlist.m3u8')]
        with patch.object(limits.subprocess, 'Popen', side_effect=OSError('launch failed')):
            with patch.object(limits, 'remove_stream_directory', side_effect=OSError('cleanup failed')):
                with self.assertRaises(limits.JobCapacityError):
                    self.budget.start(command, streams, 'failed', directory, self.outputs)
        self.assertTrue(directory.exists())
        self.assertEqual(len(self.budget.jobs), 1)
        with self.budget._connection() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM jobs').fetchone()[0], 1)
        self.budget.reap()
        self.assertFalse(directory.exists())
        self.assertEqual(streams, {})
        process, directory = self.start(streams)
        with patch.object(self.budget, 'release', side_effect=sqlite3.OperationalError('database busy')):
            with self.assertRaises(limits.JobCapacityError):
                self.budget.stop(streams, 'test')
        self.assertIsNotNone(process.poll())
        self.assertEqual(len(self.budget.jobs), 1)
        self.budget.reap()
        self.assertEqual(streams, {})

    def test_failed_watch_startup_releases_its_record_immediately(self):
        module = self.module('proxy.py')
        def failed_process(arguments, **kwargs):
            process = self.real_popen([sys.executable, '-c', 'import sys;sys.exit(1)'], **kwargs)
            process.wait(timeout=3)
            self.processes.append(process)
            return process
        with patch.object(limits.subprocess, 'Popen', side_effect=failed_process):
            response = module.app.test_client().get('/watch?url=https://fixture.invalid/video')
        self.assertEqual(response.status_code, 500)
        self.assertEqual(module.STREAMS, {})
        self.assertEqual(len(self.budget.jobs), 0)

    def test_deadline_and_output_threshold_terminate_and_clean(self):
        for trigger in ['deadline', 'output', 'missing-directory']:
            with self.subTest(trigger=trigger):
                streams = {}
                process, directory = self.start(streams)
                if trigger == 'deadline':
                    self.budget.jobs[streams['test']['lease']]['deadline'] = time.monotonic() - 1
                elif trigger == 'output':
                    self.budget.max_bytes = 16
                    (directory / 'segment_001.ts').write_bytes(b'x' * 17)
                else:
                    directory.rmdir()
                self.budget.reap()
                self.assertIsNotNone(process.poll())
                self.assertFalse(directory.exists())
                self.assertEqual(streams, {})

    def test_finished_output_retention_and_stale_direct_cleanup(self):
        streams = {}
        first, directory = self.start(streams, 'direct')
        old_lease = streams['direct']['lease']
        second, current = self.start(streams, 'direct')
        self.assertIsNotNone(first.poll())
        self.assertFalse(directory.exists())
        self.assertFalse(self.budget.stop(streams, 'direct', expected_lease=old_lease))
        self.assertIsNone(second.poll())
        (current / 'playlist.m3u8').write_text('#EXTM3U\n')
        second.process.terminate()
        second.process.wait(timeout=3)
        # Simulate a normal successful end, rather than a terminated codec.
        with patch.object(second, 'poll', return_value=0):
            self.budget.reap()
        self.assertTrue(current.exists())
        lease = streams['direct']['lease']
        self.budget.jobs[lease]['finished'] = time.monotonic() - 121
        self.budget.reap()
        self.assertFalse(current.exists())
        self.assertEqual(streams, {})

    def test_head_never_launches_video_work(self):
        module = self.module('stream_proxy.py')
        with patch.object(limits.subprocess, 'Popen', side_effect=AssertionError('No launch')):
            self.assertEqual(module.app.test_client().head('/stream?url=https://fixture.invalid/one').status_code, 200)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg is required for the real codec/HLS control')
    def test_real_ffmpeg_accepts_job_flags_and_hls_contract(self):
        directory = self.outputs / 'codec'
        fixture = self.root / 'fixture.mp4'
        generated = subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
                   '-filter_threads', '1', '-f', 'lavfi', '-i', 'testsrc=size=128x128:rate=10',
                   '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000',
                   '-t', '1', '-c:v', 'libx264', '-threads', '2', '-pix_fmt', 'yuv420p',
                   '-c:a', 'aac', str(fixture)], capture_output=True, timeout=15)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        command = ['ffmpeg', '-re', '-i', str(fixture),
                   '-c:v', 'libx264', '-profile:v', 'main', '-level', '3.1',
                   '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000', '-ac', '2',
                   '-f', 'hls', '-hls_time', '2', '-hls_list_size', '6', str(directory / 'playlist.m3u8')]
        streams = {}
        process = self.budget.start(command, streams, 'codec', directory, self.outputs)
        deadline = time.monotonic() + 15
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(process.poll(), 0, process.stderr.read())
        self.assertIn('#EXTM3U', (directory / 'playlist.m3u8').read_text())
        self.assertTrue(list(directory.glob('*.ts')))
        self.budget.reap()
        self.assertTrue(directory.exists())


if __name__ == '__main__':
    unittest.main()
