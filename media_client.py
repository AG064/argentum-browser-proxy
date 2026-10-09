import json
import socket


def exchange(data):
    encoded=json.dumps(data,separators=(',',':')).encode()+b'\n'
    if len(encoded)>65536:raise ValueError('Media metadata exceeds limit')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
        connection.settimeout(5);connection.connect('/runtime/media.sock');connection.sendall(encoded)
        with connection.makefile('rb') as stream:
            result=json.loads(stream.readline(65537))
    if 'error' in result:raise ValueError(result['error'])
    return result


def register(url,cookies):return exchange(dict(url=url,cookies=cookies))
def unregister(cap):return exchange(dict(action='delete',cap=cap))


class PreparedCommand(list):
    media_cap=None
