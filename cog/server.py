
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import json
import threading
import time
import re
import socket
from urllib.parse import urlparse

from cog.templates import render_index_page, render_graph_row, render_status_page


try:
    from importlib.metadata import version as pkg_version
    COGDB_VERSION = pkg_version('cogdb')
except Exception:
    COGDB_VERSION = "dev"


_server_registry = {}  # port -> CogDBServer
_registry_lock = threading.Lock()


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class CogDBRequestHandler(BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        pass
    
    def _send_json(self, data, status=200):
        pass
    
    def _send_html(self, html, status=200):
        pass
    
    def _read_json_body(self):
        pass
    
    def _get_local_ip(self):
        pass
    
    def _parse_path(self):
        pass
    
    def _get_share_url(self):
        pass
    
    def _get_graph_state(self, graph_name):
        pass
    
    def do_OPTIONS(self):
        pass
    
    def do_GET(self):
        pass
    
    def do_POST(self):
        pass
    
    def _handle_index_page(self):
        pass
    
    def _handle_status_page(self, graph_name, state):
        pass
    
    def _handle_stats(self, graph_name, state):
        pass
    
    def _handle_query(self, graph_name, state):
        pass
    
    def _execute_query(self, graph, query_str):
        pass
    
    def _handle_mutate(self, graph_name, state):
        pass


class CogDBServer:
    
    def __init__(self, port=8080, host='0.0.0.0'):
        self.port = port
        self.host = host
        self.server = None
        self.thread = None
        self._running = False
        self._graphs = {}  # graph_name -> state
        self._lock = threading.Lock()
    
    def register_graph(self, graph, writable=False):
        pass
    
    def unregister_graph(self, graph_name):
        """Unregister a graph. Returns True if server should shutdown."""
        with self._lock:
            if graph_name in self._graphs:
                del self._graphs[graph_name]
                if self.server:
                    self.server.cog_graphs = self._graphs
            return len(self._graphs) == 0
    
    def has_graph(self, graph_name):
        pass
    
    def start(self, blocking=False):
        pass
    
    def stop(self):
        """Stop the HTTP server and release the port."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        self._running = False
        self._graphs.clear()
    
    @property
    def url(self):
        pass
    
    @property
    def is_running(self):
        pass


def get_or_create_server(port, host='0.0.0.0'):
    pass


def unregister_from_server(port, graph_name):
    """Unregister a graph from a server. Shuts down server if empty."""
    with _registry_lock:
        if port not in _server_registry:
            return
        
        server = _server_registry[port]
        should_shutdown = server.unregister_graph(graph_name)
        
        if should_shutdown:
            server.stop()
            del _server_registry[port]


def stop_server(port=8080):
    pass
