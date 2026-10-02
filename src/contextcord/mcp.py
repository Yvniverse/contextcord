"""MCP stdio transport, protocol 2025-11-25, deliberately local only."""
import json
import sys

from . import MCP_SERVER_ID, __version__
from .service import HarnessService

SUPPORTED = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05')
MAX_MESSAGE = 1024 * 1024


class Server:
    def __init__(self, service):
        self.service = service
        self.initialized = False
        self.negotiated = False

    def handle(self, message):
        request_id = message.get('id') if isinstance(message, dict) else None

        def error(code, text):
            return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': code, 'message': text}}

        if (not isinstance(message, dict) or message.get('jsonrpc') != '2.0'
                or not isinstance(message.get('method'), str)
                or ('id' in message and (isinstance(request_id, bool) or not isinstance(request_id, (int,str))))):
            return error(-32600, 'Invalid Request')
        method = message['method']
        if 'id' not in message:
            if method == 'notifications/initialized' and self.negotiated:
                self.initialized = True
            return None
        params = message.get('params', {})
        if not isinstance(params, dict):
            return error(-32602, 'Invalid params')
        if method == 'initialize':
            if self.negotiated:
                return error(-32600, 'Already initialized')
            if not isinstance(params.get('protocolVersion'), str) or not isinstance(params.get('capabilities'), dict) or not isinstance(params.get('clientInfo'), dict):
                return error(-32602, 'Invalid initialize params')
            self.negotiated = True
            result = {'protocolVersion': params['protocolVersion'] if params['protocolVersion'] in SUPPORTED else SUPPORTED[0],
                      'capabilities': {'tools': {'listChanged': False}},
                      'serverInfo': {'name': MCP_SERVER_ID, 'version': __version__},
                      'instructions': 'ContextCord repository-scoped continuity, policy and verified engineering evidence.'}
        elif method == 'ping':
            result = {}
        elif not self.initialized:
            return error(-32002, 'Server not initialized')
        elif method == 'tools/list':
            if params.get('cursor'):
                return error(-32602, 'Unknown cursor')
            result = {'tools': self.service.tools()}
        elif method == 'tools/call':
            name = params.get('name')
            if not isinstance(name, str) or name not in {t['name'] for t in self.service.tools()}:
                return error(-32602, 'Unknown tool')
            try:
                value = self.service.call(name, params.get('arguments', {}))
                result = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}],
                          'structuredContent': value, 'isError': value.get('status') in {'FAIL','BLOCKED','ERROR'}}
            except (ValueError, RuntimeError, OSError) as exc:
                result = {'content': [{'type': 'text', 'text': str(exc)}], 'isError': True}
        else:
            return error(-32601, 'Method not found')
        return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


def serve(repo, *, allow_mutations=False, input_stream=None, output_stream=None):
    incoming = input_stream or sys.stdin.buffer
    outgoing = output_stream or sys.stdout
    server = Server(HarnessService(repo, allow_mutations=allow_mutations))
    while True:
        line = incoming.readline(MAX_MESSAGE + 1)
        if not line:
            break
        if len(line) > MAX_MESSAGE:
            # Stop before interpreting the tail as a new request.
            outgoing.write(json.dumps({'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':'Message too large'}}) + '\n')
            outgoing.flush()
            return 2
        try:
            request = json.loads(line)
        except (ValueError, UnicodeError):
            response = {'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Parse error'}}
        else:
            response = server.handle(request)
        if response is not None:
            outgoing.write(json.dumps(response, ensure_ascii=False, separators=(',', ':')) + '\n')
            outgoing.flush()
    return 0
