import json
import subprocess
import time
rows=json.loads(subprocess.check_output(['ip','-j','address']))
interface=next(row['ifname'] for row in rows if any(a['local']=='51.77.0.2' for a in row.get('addr_info',[])))
subprocess.run(['ip','route','replace','default','via','51.77.0.1','dev',interface],check=True)
while True:time.sleep(60)
