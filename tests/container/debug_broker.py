import json,socket,ipaddress
from egress_broker import DestinationPolicy,ip_command,route_source
result={}
try:
 records=socket.getaddrinfo('public.fixture.test',80,type=socket.SOCK_STREAM)
 result['addresses']=[record[4][0] for record in records]
 for address in result['addresses']:
  family='-6' if ':' in address else '-4'
  result[address]={'default':ip_command(family,'route','show','default'),'matching':ip_command(family,'route','show','match',address),'route':ip_command(family,'route','get',address)}
  try:result[address]['source']=route_source(ipaddress.ip_address(address))
  except Exception as error:result[address]['error']=str(error)
except Exception as error:result['resolution_error']=repr(error)
print(json.dumps(result))
