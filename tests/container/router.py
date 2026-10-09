import subprocess,time
subprocess.run(['iptables','-P','FORWARD','ACCEPT'],check=True)
while True:time.sleep(60)
