import array
import math
import heapq
import logging
from math import isclose

from cog.core import Record
from cog.embedding_providers import EMBEDDING_PROVIDERS, _chunked

try:
    import simsimd
    _HAS_SIMSIMD = True
except ImportError:
    _HAS_SIMSIMD = False

logger = logging.getLogger(__name__)


class EmbeddingMixin:

    def put_embedding(self, text, embedding):
        """
        Saves a text embedding.
        """
        assert isinstance(text, str), "text must be a string"
        if self._cloud:
            self._cloud_client.mutate_put_embedding(text, embedding)
            return
        self.cog.use_namespace(self.graph_name).use_table(self.config.EMBEDDING_SET_TABLE_NAME).put(Record(
            text, embedding))

    def get_embedding(self, text):
        pass

    def delete_embedding(self, text):
        """
        Deletes a text embedding.
        """
        assert isinstance(text, str), "text must be a string"
        if self._cloud:
            self._cloud_client.mutate_delete_embedding(text)
            return
        self.cog.use_namespace(self.graph_name).use_table(self.config.EMBEDDING_SET_TABLE_NAME).delete(
            text)

    def put_embeddings_batch(self, text_embedding_pairs):
        pass

    def scan_embeddings(self, limit=100):
        pass

    def embedding_stats(self):
        pass

    def k_nearest(self, text, k=10):
        pass

    def sim(self, text, operator, threshold, strict=False):
        pass

    def _cosine_distance(self, x, y):
        pass

    def _cosine_similarity(self, text1, text2):
        pass

    def load_glove(self, filepath, limit=None, batch_size=1000):
        pass

    def load_gensim(self, model, limit=None, batch_size=1000):
        pass

    def _auto_embed(self, text):
        pass

    def vectorize(self, texts=None, provider="cogdb", batch_size=100, **kwargs):
        pass
