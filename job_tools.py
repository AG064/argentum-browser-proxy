"""Bound helper output and keep helper descendants under the job supervisor."""
import os
from pathlib import Path
import subprocess
import threading
import time
from types import SimpleNamespace
import isolation_runtime as runtime


def run_guarded(command, *, seconds=60, cwd=None):
    arguments = runtime.guarded_command(command, seconds)
    process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, cwd=cwd, start_new_session=True)
    result = {'stdout': bytearray(), 'stderr': bytearray()}
    overflow = threading.Event()
    def drain(name, stream, maximum):
        try:
            while True:
                data = stream.read(1024)
                if not data:
                    return
                if len(result[name])+len(data) > maximum:
                    overflow.set()
                    return
                result[name].extend(data)
        finally:
            stream.close()
    threads = [threading.Thread(target=drain, args=(name, getattr(process, name), maximum), daemon=True)
               for name,maximum in [('stdout', 65536), ('stderr', 4096)]]
    for thread in threads:
        thread.start()
    deadline = time.monotonic()+seconds+5
    while process.poll() is None and not overflow.is_set() and time.monotonic() < deadline:
        time.sleep(0.05)
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
            runtime.fail_worker()
    for thread in threads:
        thread.join(timeout=1)
    if process.returncode < 0 or process.returncode == 70:
        runtime.fail_worker()
    return SimpleNamespace(returncode=process.returncode if not overflow.is_set() else 1,
        stdout=bytes(result['stdout']).decode('utf-8', errors='replace'),
        stderr=bytes(result['stderr']).decode('utf-8', errors='replace'))
