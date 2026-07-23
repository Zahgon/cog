
from cog.database import out_nodes, in_nodes

_PRESENT = True

DEFAULT_PAGE_SIZE = 50_000


class MemoryView:

    def __init__(self, table, page_size=None, shared_out=None, shared_in=None):
        self._table = table
        self._page_size = page_size or DEFAULT_PAGE_SIZE
        self._out = shared_out if shared_out is not None else {}
        self._in = shared_in if shared_in is not None else {}
        self._shared = shared_out is not None
        if self._shared:
            self._scanner = None
            self._fully_loaded = True
        else:
            self._scanner = table.indexer.scanner(table.store)
            self._fully_loaded = False
            self._load_page()

    def _load_page(self):
        pass

    def _ingest_record(self, record):
        pass

    def _demand_load(self, node_id, direction):
        pass

    def load_more(self):
        pass

    @property
    def fully_loaded(self):
        pass

    def add_edge(self, src, tgt):
        o = self._out.get(src)
        if o is None:
            self._out[src] = {tgt: _PRESENT}
        else:
            o[tgt] = _PRESENT
        i = self._in.get(tgt)
        if i is None:
            self._in[tgt] = {src: _PRESENT}
        else:
            i[src] = _PRESENT

    def remove_edge(self, src, tgt):
        o = self._out.get(src)
        if o is not None:
            o.pop(tgt, None)
        i = self._in.get(tgt)
        if i is not None:
            i.pop(src, None)

    def replace_out(self, src, new_tgt):
        old = self._out.get(src)
        if old:
            for t in old:
                i = self._in.get(t)
                if i is not None:
                    i.pop(src, None)
        self._out[src] = {new_tgt: _PRESENT}
        i = self._in.get(new_tgt)
        if i is None:
            self._in[new_tgt] = {src: _PRESENT}
        else:
            i[src] = _PRESENT

    def clear(self):
        self._out.clear()
        self._in.clear()
        if not self._shared:
            self._scanner = self._table.indexer.scanner(self._table.store)
            self._fully_loaded = False

    def get_out(self, node_id):
        pass

    def get_in(self, node_id):
        pass
