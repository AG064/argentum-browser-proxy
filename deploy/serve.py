import importlib
import sys
sys.path.insert(0, '/app')
from waitress import serve
import isolation_runtime
isolation_runtime.require_isolation()
application = importlib.import_module(sys.argv[1]).app
serve(application, host='0.0.0.0', port=int(sys.argv[2]), threads=4, connection_limit=32,
      channel_timeout=30, max_request_body_size=32*1024*1024,
      max_request_header_size=65536, inbuf_overflow=1024*1024, outbuf_overflow=1024*1024,
      ident='Argentum')
