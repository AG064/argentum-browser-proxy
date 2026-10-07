import ast
import os
from pathlib import Path
import tempfile
import types
import unittest
from werkzeug.exceptions import NotFound
from path_security import contained_file, remove_stream_directory


class FileAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.stream = self.root / 'stream'
        self.stream.mkdir()
        (self.stream / 'playlist.m3u8').write_text('#EXTM3U\nsegment_001.ts\n')
        (self.stream / 'segment_001.ts').write_bytes(b'media')
        (self.root / 'private.txt').write_text('private marker')

    def tearDown(self):
        self.temp.cleanup()

    def test_containment_and_valid_generated_files(self):
        for filename in ['../private.txt', '../private.ts', str(self.root / 'private.txt'), '..\\private.txt', 'C:/private.ts', 'segment_001.ts:other', 'NUL.ts']:
            with self.assertRaises(NotFound):
                contained_file(self.stream, filename, hls=True)
        self.assertEqual(Path(contained_file(self.stream, 'segment_001.ts', hls=True)).read_bytes(), b'media')
        with self.assertRaises(NotFound):
            contained_file(self.stream, 'missing.ts', hls=True)

    def test_symlink_cannot_escape(self):
        if os.name == 'nt':
            self.skipTest('File symlinks require Windows privileges')
        (self.stream / 'secret.ts').symlink_to(self.root / 'private.txt')
        with self.assertRaises(NotFound):
            contained_file(self.stream, 'secret.ts', hls=True)

    def test_all_hls_routes_use_containment(self):
        source_root = Path(__file__).resolve().parents[1]
        for filename, route in [('proxy.py', '/hls/test/'), ('stream_proxy.py', '/hls/test/'), ('browser_app.py', '/browser/hls/test/')]:
            tree = ast.parse((source_root / filename).read_text(encoding='utf-8'))
            for statement in tree.body:
                if isinstance(statement, ast.Assign) and any(isinstance(item, ast.Name) and item.id == 'STREAM_DIR' for item in statement.targets):
                    statement.value = ast.Constant(str(self.root / filename.replace('.', '-')))
            module = types.ModuleType('test_' + filename.replace('.', '_'))
            module.__file__ = str(source_root / filename)
            exec(compile(ast.fix_missing_locations(tree), module.__file__, 'exec'), module.__dict__)
            module.STREAMS['test'] = {'segment_dir': str(self.stream)}
            client = module.app.test_client()
            self.assertEqual(client.get(route + '../private.txt').status_code, 404, filename)
            self.assertEqual(client.get(route + '..%2fprivate.ts').status_code, 404, filename)
            response = client.get(route + 'segment_001.ts')
            self.assertEqual(response.status_code, 200, filename)
            self.assertEqual(response.data, b'media')
            response.close()
            if filename == 'proxy.py':
                module.STATIC_DIR = str(self.stream)
                self.assertEqual(client.get('/static/../private.txt').status_code, 404)
                for name in ['hls_files', 'serve_hls']:
                    with module.app.test_request_context():
                        with self.assertRaises(NotFound):
                            getattr(module, name)('test', '../private.txt')

    def test_cleanup_refuses_root_and_other_directories(self):
        with self.assertRaises(ValueError):
            remove_stream_directory(self.root, self.root)
        sibling = self.root.parent / (self.root.name + '-other')
        sibling.mkdir()
        try:
            with self.assertRaises(ValueError):
                remove_stream_directory(sibling, self.root)
            self.assertTrue(sibling.exists())
        finally:
            sibling.rmdir()
        remove_stream_directory(self.stream, self.root)
        self.assertFalse(self.stream.exists())
