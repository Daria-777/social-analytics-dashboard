"""Single-use OAuth callback socket shared by the two local CLI helpers."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import socket
from threading import Timer
import time
from urllib.parse import urlsplit


class LoopbackCallback:
    def __init__(self, local_uri, expected_uri, state, parser, *, timeout=300):
        target=urlsplit(local_uri)
        if target.scheme!='http' or target.hostname not in ('127.0.0.1','localhost') or not target.port or target.query or target.fragment or target.username or target.password or not 0 < timeout <= 600:
            raise ValueError('Fixed HTTP loopback callback required')
        if target.path != urlsplit(expected_uri).path:
            raise ValueError('Callback paths must match')
        self.uri = expected_uri
        self.target = target
        self.parser = parser
        self.state = state
        self.deadline = min(time.monotonic() + timeout, state.deadline)
        self.server = self.timer = self.connection = None
        self.done = self.closed = False
        self.code = self.error = None

    def __enter__(self):
        if self.server is not None or self.closed or self.state.used:
            raise ValueError('Fresh desktop callback required')
        owner = self

        class Receiver(HTTPServer):
            def get_request(self):
                connection, address = super().get_request()
                owner.connection = connection
                remaining = owner.deadline - time.monotonic()
                if remaining <= 0:
                    connection.close()
                    raise OSError('Callback expired')
                connection.settimeout(min(1, remaining))
                return connection, address

            def handle_error(self, request, client_address):
                # Standard server tracebacks can include request information.
                pass

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass

            def answer(self, status):
                payload = ('Authorization response received. Return to the local helper.' if status == 200 else 'Authorization response rejected. Return to the local helper.').encode()
                self.send_response(status)
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(payload)

            def send_error(self, code, message=None, explain=None):
                # Base handler error pages can echo raw request targets.
                self.answer(code)

            def do_GET(self):
                if owner.done or owner.closed:
                    self.answer(410); return
                try:
                    uri = urlsplit(self.path)
                    hosts = self.headers.get_all('Host', [])
                    if uri.scheme or uri.netloc or uri.fragment or len(self.path) > 8192 or len(hosts) != 1 or hosts[0].lower() != owner.target.netloc.lower():
                        self.answer(400); return
                    if uri.path != owner.target.path:
                        self.answer(404); return
                    owner.code = owner.parser(owner.uri + '?' + uri.query, owner.uri, owner.state)
                except ValueError:
                    owner.error = ValueError('Local authorization response rejected')
                    owner.done = True
                    self.answer(400); return
                owner.done = True
                self.answer(200)

            def do_POST(self): self.answer(405)

        # Fixed IPv4 loopback. Binding failure aborts, never changes host/port.
        self.server = Receiver(('127.0.0.1', self.target.port), Handler)
        self.timer = Timer(max(0, self.deadline - time.monotonic()), self._expire)
        self.timer.daemon = True
        self.timer.start()
        return self

    def _expire(self):
        # Enforce an absolute deadline even while a client slowly sends headers.
        self._close_connection()

    def _close_connection(self):
        if self.connection is not None:
            try: self.connection.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            self.connection.close()

    def wait(self):
        if self.server is None or self.closed:
            raise ValueError('Local callback is not listening')
        try:
            while not self.done:
                remaining = self.deadline - time.monotonic()
                if remaining <= 0: raise TimeoutError('Local authorization timed out')
                self.server.timeout = min(.2, remaining)
                self.server.handle_request()
            if time.monotonic() >= self.deadline: raise TimeoutError("Local authorization timed out")
            if self.error is not None: raise self.error
            return self.code
        finally:
            self.close()

    def close(self):
        self.closed = True
        if self.timer is not None:
            self.timer.cancel()
            self.timer.join(timeout=1)
        self._close_connection()
        if self.server is not None: self.server.server_close()

    def __exit__(self, *_): self.close()
