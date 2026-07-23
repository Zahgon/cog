import json
import logging
import re
import threading
import urllib.request
import urllib.error

logger = logging.getLogger("cog.share")


def _validate_path(path):
    pass


def _http_request(method, url, body=None, timeout=25, extra_headers=None):
    pass


class ShareInfo:
    def __init__(self):
        self.url = None
        self.session_id = None
        self._ready = threading.Event()
        self._error = None
    
    def wait(self, timeout=10):
        pass


def start_share(local_port, local_host="127.0.0.1", relay_url=None):
    pass
