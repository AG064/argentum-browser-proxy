"""Shared admission and lifecycle controls for proxy video jobs.

These controls are defense in depth. They do not replace OS resource quotas or
outbound network isolation for an Internet-facing deployment.
"""
import atexit
from collections import deque
from contextlib import contextmanager
import io
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import threading
import time
import uuid
from flask import g, has_request_context, Response, send_file
from path_security import remove_stream_directory, contained_file
from werkzeug.exceptions import NotFound


class JobCapacityError(RuntimeError):
    pass


class ManagedProcess:
    def __init__(self, process):
        self.process = process
        self.pid = process.pid
        self.chunks = deque()
        self.bytes = 0
        self.lock = threading.Lock()
        self.reader = threading.Thread(target=self._drain, daemon=True)

    def start_reader(self):
        self.reader.start()

    def _drain(self):
        try:
            while True:
                chunk = self.process.stderr.read(1024)
                if not chunk:
                    break
                with self.lock:
                    self.chunks.append(chunk)
                    self.bytes += len(chunk)
                    while self.bytes > 4096:
                        self.bytes -= len(self.chunks.popleft())
        finally:
            self.process.stderr.close()

    @property
    def stderr(self):
        if self.poll() is not None and self.reader.ident is not None:
            self.reader.join(timeout=0.5)
        with self.lock:
            return io.BytesIO(b''.join(self.chunks))

    def poll(self):
        return self.process.poll()

    def stop(self):
        if self.poll() is None:
            if os.name == 'posix':
                os.killpg(self.pid, signal.SIGTERM)
            else:
                self.process.terminate()
            try:
                self.process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                if os.name == 'posix':
                    os.killpg(self.pid, signal.SIGKILL)
                else:
                    self.process.kill()
                self.process.wait(timeout=2)
        if self.reader.ident is not None:
            self.reader.join(timeout=0.5)


class JobBudget:
    def __init__(self, state_directory=None, *, max_active=2, max_records=6,
                 max_seconds=14400, max_bytes=128 * 1024 * 1024,
                 retention_seconds=120, interval=0.5):
        if not (1 <= max_active <= max_records <= 32 and 0 < max_seconds <= 14400
                and 0 < max_bytes <= 128 * 1024 * 1024 and 0 <= retention_seconds <= 120):
            raise ValueError('Invalid job limits')
        directory = Path(state_directory or os.environ.get('ARGENTUM_PROXY_JOB_STATE_DIR',
                         str(Path(__file__).resolve().with_name('.runtime'))))
        if directory.is_symlink():
            raise ValueError('Job state must not be a symlink')
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == 'posix':
            stat = directory.stat()
            if stat.st_uid != os.getuid() or stat.st_mode & 0o022:
                raise ValueError('Job state must be owned by the server and not writable by others')
        self.database = directory / 'jobs.sqlite3'
        if self.database.is_symlink():
            raise ValueError('Job database must not be a symlink')
        self.max_active, self.max_records = max_active, max_records
        self.max_seconds, self.max_bytes = max_seconds, max_bytes
        self.retention_seconds, self.interval = retention_seconds, interval
        self.lock = threading.RLock()
        self.jobs = {}
        self.closed = threading.Event()
        with self._connection() as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS jobs (lease TEXT PRIMARY KEY, state TEXT NOT NULL)')
        self.monitor = threading.Thread(target=self._monitor, daemon=True)
        self.monitor.start()
        atexit.register(self.close)

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.database, timeout=1)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def reserve(self):
        lease = uuid.uuid4().hex
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            total, active = connection.execute(
                "SELECT count(*), coalesce(sum(state != 'retained'), 0) FROM jobs").fetchone()
            if total >= self.max_records or active >= self.max_active:
                raise JobCapacityError('Video job capacity reached; stop an existing stream or retry later')
            connection.execute('INSERT INTO jobs VALUES (?, ?)', (lease, 'pending'))
        return lease

    def release(self, lease):
        if lease:
            with self._connection() as connection:
                connection.execute('DELETE FROM jobs WHERE lease = ?', (lease,))

    def install(self, app, endpoints):
        @app.errorhandler(JobCapacityError)
        def job_cleanup_failed(error):
            return {'error': str(error)}, 503, {'Retry-After': '5'}

        @app.before_request
        def admit_video_work():
            from flask import request
            if request.endpoint not in endpoints:
                return None
            if request.method == 'HEAD':
                return '', 200
            try:
                g.video_lease = self.reserve()
                g.video_job = None
            except (JobCapacityError, sqlite3.Error):
                return {'error': 'Video job capacity reached; stop an existing stream or retry later'}, 503, {'Retry-After': '5'}

        @app.after_request
        def release_unused_reservation(response):
            lease = getattr(g, 'video_lease', None)
            job = getattr(g, 'video_job', None)
            if job is None:
                self.release(lease)
            elif response.status_code >= 400:
                try:
                    self.stop(job['streams'], job['key'], expected_lease=job['info']['lease'])
                except JobCapacityError:
                    from flask import jsonify
                    response = jsonify(error='Stream cleanup is not confirmed; retry later')
                    response.status_code = 503
                    response.headers['Retry-After'] = '5'
            return response

        @app.teardown_request
        def release_failed_reservation(error):
            if error is not None:
                job = getattr(g, 'video_job', None)
                if job:
                    self.stop(job['streams'], job['key'], expected_lease=job['info']['lease'])
                else:
                    self.release(getattr(g, 'video_lease', None))

    def start(self, command, streams, key, segment_dir, root, metadata=None, env=None):
        lease = getattr(g, 'video_lease', None) if has_request_context() else None
        own_lease = lease is None
        if own_lease:
            lease = self.reserve()
        directory = Path(segment_dir)
        entry = None
        try:
            with self.lock:
                self.stop(streams, key)
                directory.mkdir(mode=0o700, exist_ok=False)
                info = dict(metadata or {}, process=None, segment_dir=str(directory),
                            started=time.time(), lease=lease)
                entry = {'streams': streams, 'key': key, 'info': info, 'root': root,
                         'deadline': time.monotonic() + self.max_seconds, 'finished': None,
                         'failed': False}
                self.jobs[lease] = entry
                streams[key] = info
                if has_request_context():
                    g.video_job = entry
                arguments = list(command)
                arguments[1:1] = ['-nostdin', '-hide_banner', '-loglevel', 'error', '-filter_threads', '1']
                arguments[arguments.index('-i'):arguments.index('-i')] = ['-threads', '2', '-rw_timeout', '15000000']
                arguments[-1:-1] = ['-threads', '2']
                process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env,
                    start_new_session=os.name == 'posix',
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                info['process'] = process
                managed = ManagedProcess(process)
                info['process'] = managed
                managed.start_reader()
                return managed
        except Exception:
            if entry is not None:
                entry['failed'] = True
                self.stop(streams, key, expected_lease=lease)
            else:
                self.release(lease)
            raise

    def stop(self, streams, key, *, expected_lease=None):
        with self.lock:
            info = streams.get(key)
            if not info:
                return False
            lease = info.get('lease')
            if expected_lease is not None and lease != expected_lease:
                return False
            entry = self.jobs.get(lease)
            if entry is None:
                return False
            try:
                process = info['process']
                if isinstance(process, ManagedProcess):
                    process.stop()
                elif process is not None:
                    process.kill()
                    process.wait(timeout=2)
                directory = Path(info['segment_dir'])
                if directory.exists():
                    remove_stream_directory(directory, entry['root'])
                self.release(lease)
            except (OSError, ValueError, subprocess.TimeoutExpired, sqlite3.Error):
                raise JobCapacityError('Stream cleanup is not confirmed; retry later') from None
            streams.pop(key, None)
            self.jobs.pop(lease, None)
            return True

    def snapshot(self, streams, key):
        with self.lock:
            info = streams.get(key)
            return dict(info) if info else None

    def serve_hls(self, streams, key, filename):
        with self.lock:
            info = streams.get(key)
            if not info:
                raise NotFound()
            path = contained_file(info['segment_dir'], filename, hls=True)
            try:
                if filename.endswith('.m3u8'):
                    return Response(Path(path).read_bytes(), mimetype='application/vnd.apple.mpegurl',
                                    headers={'Cache-Control': 'no-cache'})
                return send_file(path, mimetype='video/mp2t')
            except FileNotFoundError:
                raise NotFound() from None

    def _monitor(self):
        while not self.closed.wait(self.interval):
            self.reap()

    def reap(self):
        with self.lock:
            for lease, entry in list(self.jobs.items()):
                if self.jobs.get(lease) is not entry:
                    continue
                info = entry['info']
                try:
                    now = time.monotonic()
                    if entry['failed'] or now >= entry['deadline']:
                        self.stop(entry['streams'], entry['key'])
                        continue
                    directory = Path(info['segment_dir'])
                    size = sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
                    if size > self.max_bytes:
                        self.stop(entry['streams'], entry['key'])
                    elif info['process'].poll() is not None:
                        if info['process'].poll() != 0:
                            self.stop(entry['streams'], entry['key'])
                            continue
                        if entry['finished'] is None:
                            entry['finished'] = now
                            with self._connection() as connection:
                                connection.execute("UPDATE jobs SET state = 'retained' WHERE lease = ?", (lease,))
                        elif now - entry['finished'] >= self.retention_seconds:
                            self.stop(entry['streams'], entry['key'])
                except (OSError, sqlite3.Error, subprocess.TimeoutExpired, JobCapacityError):
                    # Keep ownership and capacity if cleanup cannot be confirmed.
                    try:
                        self.stop(entry['streams'], entry['key'], expected_lease=lease)
                    except JobCapacityError:
                        continue

    def close(self):
        self.closed.set()
        with self.lock:
            for entry in list(self.jobs.values()):
                self.stop(entry['streams'], entry['key'])


JOB_BUDGET = JobBudget()
