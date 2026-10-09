"""Exit the PID namespace when a service or its supervisor fails."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
sys.path.insert(0, '/app')
import isolation_runtime

stopping = False


def stop(signum, frame):
    global stopping
    stopping = True


def main():
    isolation_runtime.require_isolation()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    processes = [subprocess.Popen([sys.executable, '/app/deploy/serve.py', module, str(port)])
                 for module,port in [('proxy',8765), ('browser_app',8767), ('stream_proxy',8788)]]
    processes.append(subprocess.Popen([sys.executable, '/app/media_proxy.py']))
    while not stopping and all(process.poll() is None for process in processes):
        time.sleep(0.2)
    # Namespace PID1 exits after this process; the kernel kills all descendants.
    return 1


if __name__ == '__main__':
    sys.exit(main())
