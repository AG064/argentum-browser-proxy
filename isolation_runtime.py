"""Verify the supported worker boundary before any network-capable work."""
import json
import os
from pathlib import Path
import signal
import stat
import sys
from urllib.parse import urlsplit


class IsolationUnavailable(RuntimeError):
    pass


def _integer(path):
    value = Path(path).read_text().strip()
    if value == 'max':
        raise IsolationUnavailable('A required resource limit is missing')
    return int(value)


def require_isolation():
    if sys.platform != 'linux':
        raise IsolationUnavailable('Use the isolated Linux deployment')
    path = Path('/run/argentum/isolation.json')
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022 or metadata.st_size > 8192:
            raise ValueError()
        marker = json.loads(path.read_text())
        if marker.get('version') != 1 or marker['net_namespace'] != os.readlink('/proc/self/ns/net'):
            raise ValueError()
        status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
        if os.getuid() != 10001 or int(status['CapEff'].strip(), 16) or int(status['CapBnd'].strip(), 16) or int(status['NoNewPrivs']) != 1:
            raise ValueError()
        if not 0 < _integer('/sys/fs/cgroup/memory.max') <= 1536*1024*1024 or _integer('/sys/fs/cgroup/memory.swap.max') != 0:
            raise ValueError()
        cpu, period = Path('/sys/fs/cgroup/cpu.max').read_text().split()
        if cpu == 'max' or not 0 < int(cpu) <= 2*int(period) or not 0 < _integer('/sys/fs/cgroup/pids.max') <= 256:
            raise ValueError()
        mounts = [line.split(' - ', 1) for line in Path('/proc/self/mountinfo').read_text().splitlines()]
        for directory, maximum in [('/runtime', 256*1024*1024), ('/tmp', 64*1024*1024), ('/dev/shm', 128*1024*1024)]:
            mount = next(row for row in mounts if row[0].split()[4] == directory)
            volume = os.statvfs(directory)
            if mount[1].split()[0] != 'tmpfs' or volume.f_blocks*volume.f_frsize > maximum or not 0 < volume.f_files <= 16384:
                raise ValueError()
        proxy = urlsplit(marker['proxy'])
        if proxy.scheme != 'http' or proxy.hostname != marker['broker_ip'] or proxy.port != 3128 or proxy.path:
            raise ValueError()
        if marker['supervisor_pid'] < 2:
            raise ValueError()
        return marker
    except (OSError, ValueError, KeyError, StopIteration, TypeError) as error:
        raise IsolationUnavailable('The required worker boundary is unavailable') from error


def fail_worker():
    marker = require_isolation()
    os.kill(marker['supervisor_pid'], signal.SIGTERM)
    raise IsolationUnavailable('Worker supervision failed; restart the isolated deployment')


def proxies():
    proxy = require_isolation()['proxy']
    return {'http': proxy, 'https': proxy}


def browser_options():
    return dict(headless=True, channel='chromium', chromium_sandbox=True,
                proxy={'server': require_isolation()['proxy']},
                args=['--proxy-bypass-list=<-loopback>', '--disable-quic'])


def guarded_command(command, seconds):
    require_isolation()
    if not 0 < seconds <= 14400:
        raise ValueError('Invalid worker deadline')
    return [sys.executable, str(Path(__file__).with_name('process_guard.py')), str(seconds), '--', *command]


def ffmpeg_options(command, cookies=None):
    from web_security import validate_http_url
    from cookie_security import ffmpeg_cookies
    position = command.index('-i')
    url = validate_http_url(command[position+1])
    options = ['-protocol_whitelist', 'http,https,tcp,tls,crypto,data',
               '-http_proxy', require_isolation()['proxy'],
               '-tls_verify', '1', '-ca_file', '/etc/ssl/certs/ca-certificates.crt']
    if cookies:
        options += ['-cookies', ffmpeg_cookies(cookies, url)]
    return command[:position]+options+command[position:]
