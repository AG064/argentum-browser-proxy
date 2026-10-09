"""Linux job supervisor. Adopt and reap escaped descendants before exit."""
import ctypes
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

stopping = False


def stop_signal(signum, frame):
    global stopping
    stopping = True


def children():
    processes = {}
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry/'stat').read_text().rsplit(') ', 1)[1].split()
            processes[int(entry.name)] = (int(fields[1]), fields[19])
        except (OSError, IndexError, ValueError):
            continue
    owned = {os.getpid()}
    for _ in range(256):
        added = {pid for pid,(parent,start) in processes.items() if parent in owned}-owned
        if not added:
            break
        owned.update(added)
    return {pid:processes[pid][1] for pid in owned if pid != os.getpid()}


def kill_children():
    deadline = time.monotonic()+3
    while time.monotonic() < deadline:
        owned = children()
        for pid, started in owned.items():
            try:
                descriptor = os.pidfd_open(pid)
                try:
                    fields = Path('/proc/'+str(pid)+'/stat').read_text().rsplit(') ',1)[1].split()
                    if fields[19] == started:
                        signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                finally:
                    os.close(descriptor)
            except (OSError, ValueError, IndexError):
                pass
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
                if pid == 0:
                    break
            except ChildProcessError:
                return True
        time.sleep(0.02)
    return not children()


def main():
    if sys.platform != 'linux' or '--' not in sys.argv:
        return 70
    limit = float(sys.argv[1])
    command = sys.argv[sys.argv.index('--')+1:]
    if not command or not 0 < limit <= 14400:
        return 70
    # PR_SET_CHILD_SUBREAPER does not require privileges.
    prctl = ctypes.CDLL(None, use_errno=True).prctl
    prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    if prctl(36, 1, 0, 0, 0) != 0:
        return 70
    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL)
    deadline = time.monotonic()+limit
    while process.poll() is None and not stopping and time.monotonic() < deadline:
        time.sleep(0.05)
    result = process.poll()
    cleaned = kill_children()
    if not cleaned:
        return 70
    return 0 if result == 0 else (124 if result is None else 1)


if __name__ == '__main__':
    sys.exit(main())
