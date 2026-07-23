
import json
import ssl
import urllib.request
import urllib.error

from . import config as cfg

_SSL_CONTEXT = None


def _get_ssl_context():
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        try:
            import certifi
            _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
        except (ImportError, OSError):
            _SSL_CONTEXT = ssl.create_default_context()
    return _SSL_CONTEXT


class CloudClient:

    MAX_BATCH_SIZE = 500  # server-side limit per request

    def __init__(self, graph_name, api_key, flush_interval=1):
        self._graph_name = graph_name
        self._api_key = api_key
        self._base_url = f"{cfg.CLOUD_URL}{cfg.CLOUD_API_PREFIX}/{graph_name}"
        self._account_url = f"{cfg.CLOUD_URL}{cfg.CLOUD_API_PREFIX}/_cog_sys__"
        self._flush_interval = flush_interval
        self._pending = []  # buffered mutations awaiting flush

    def _request(self, method, path, body=None):
        """Make an authenticated request to a graph-scoped endpoint."""
        return self._do_request(method, f"{self._base_url}{path}", body)

    def _account_request(self, method, path, body=None):
        pass

    def _do_request(self, method, full_url, body=None):
        """Shared HTTP logic for all authenticated requests."""
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(full_url, data=data, method=method)
        req.add_header("Authorization", self._api_key)
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "cogdb-python")

        try:
            with urllib.request.urlopen(req, context=_get_ssl_context()) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise PermissionError("Invalid API key")
            try:
                detail = json.loads(e.read().decode("utf-8")).get("detail", "")
            except Exception:
                detail = ""
            if e.code in (400, 422):
                raise ValueError(detail or f"Bad request ({e.code})")
            raise RuntimeError(
                f"CogDB Cloud error ({e.code})" + (f": {detail}" if detail else "")
            )
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Cannot reach CogDB Cloud at {cfg.CLOUD_URL}: {e.reason}"
            )
        
    def _mutate_batch(self, mutations):
        """Send mutations via the batch endpoint, chunking at MAX_BATCH_SIZE."""
        total_count = 0
        for i in range(0, len(mutations), self.MAX_BATCH_SIZE):
            chunk = mutations[i:i + self.MAX_BATCH_SIZE]
            result = self._request("POST", "/mutate_batch", {
                "mutations": chunk,
            })
            total_count += result.get("count", len(chunk))
        return {"ok": True, "count": total_count}

    def _mutate_one(self, mutation):
        """Send a single mutation immediately (bypasses buffer)."""
        return self._mutate_batch([mutation])

    def _enqueue(self, mutation):
        """Buffer a mutation; auto-flush when flush_interval threshold is reached."""
        self._pending.append(mutation)
        if self._flush_interval > 0 and len(self._pending) >= self._flush_interval:
            self.sync()

    def sync(self):
        """Flush all pending mutations to cloud."""
        if not self._pending:
            return
        self._mutate_batch(list(self._pending))
        self._pending.clear()

    def mutate_put(self, subject, predicate, obj, update=False, create_new_edge=False):
        self._enqueue({
            "op": "PUT", "s": str(subject), "p": str(predicate), "o": str(obj),
            "update": update, "create_new_edge": create_new_edge,
        })

    def mutate_put_batch(self, triples):
        pass

    def mutate_delete(self, subject, predicate, obj):
        self._enqueue({
            "op": "DELETE", "s": str(subject), "p": str(predicate), "o": str(obj),
        })

    def mutate_drop(self):
        self.sync()  # flush pending before destructive operation
        return self._mutate_one({"op": "DROP"})

    def mutate_truncate(self):
        self.sync()  # flush pending before destructive operation
        return self._mutate_one({"op": "TRUNCATE"})

    def mutate_put_embedding(self, word, embedding):
        return self._mutate_one({
            "op": "PUT_EMBEDDING", "word": word, "embedding": embedding,
        })

    def mutate_delete_embedding(self, word):
        return self._mutate_one({
            "op": "DELETE_EMBEDDING", "word": word,
        })

    def mutate_put_embeddings_batch(self, embeddings):
        pass

    def mutate_vectorize(self, words, provider, batch_size):
        pass

    @staticmethod
    def _quote(value):
        pass

    @classmethod
    def _chain_to_query_string(cls, chain):
        pass

    @classmethod
    def _serialize_step(cls, method, args):
        pass

    def query_chain(self, chain):
        pass

    def query_scan(self, limit, scan_type):
        pass

    def query_triples(self):
        pass

    def query_get_embedding(self, word):
        pass

    def query_scan_embeddings(self, limit):
        pass

    def query_embedding_stats(self):
        pass


    def list_graphs(self):
        pass

