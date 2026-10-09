import json
import os
from pathlib import Path
import resource
result={'uid':os.getuid(),'status':{k:v.strip() for line in Path('/proc/self/status').read_text().splitlines() if ':' in line for k,v in [line.split(':',1)] if k in ['CapEff','CapBnd','NoNewPrivs']},'fds':resource.getrlimit(resource.RLIMIT_NOFILE)}
for name in ('memory.max','memory.swap.max','pids.max','cpu.max'):
 result[name]=Path('/sys/fs/cgroup',name).read_text().strip()
result['mounts']={name:{'bytes':os.statvfs(name).f_blocks*os.statvfs(name).f_frsize,'inodes':os.statvfs(name).f_files} for name in ('/runtime','/tmp','/dev/shm')}
print(json.dumps(result))
