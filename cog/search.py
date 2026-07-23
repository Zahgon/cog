from collections import deque
import logging

from cog.database import hash_predicate

logger = logging.getLogger(__name__)


class TraversalMixin:

    def __get_adjacent(self, vertex, predicates, direction):
        pass

    def bfs(self, predicates=None, max_depth=None, min_depth=0,
            direction="out", until=None, unique=True):
        pass

    def dfs(self, predicates=None, max_depth=None, min_depth=0,
            direction="out", until=None, unique=True):
        pass
