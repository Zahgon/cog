
from cog.core import Record
import logging
import os
import os.path
from os import listdir
from os.path import isfile
from os.path import join
import pickle
import socket
import uuid
from .core import Table
from . import config
from .config import CogConfig
import xxhash
import csv
import shlex
from collections import OrderedDict



_OUT_PREFIX = b'\x00'
_IN_PREFIX = b'\x01'


def out_nodes(v):
    return _OUT_PREFIX + v.encode('utf-8') if type(v) is str else _OUT_PREFIX + v


def in_nodes(v):
    return _IN_PREFIX + v.encode('utf-8') if type(v) is str else _IN_PREFIX + v


def hash_predicate(predicate):
    return str(xxhash.xxh32(predicate, seed=2).intdigest())


def parse_tripple(tripple):
    tokens = shlex.split(tripple)
    subject = tokens[0].strip()
    predicate = tokens[1].strip()
    object = tokens[2].strip()
    context = None

    if len(tokens) > 3:  # nQuad
        context = tokens[3].strip()

    return subject, predicate, object, context


class CacheData:
    __slots__ = ('store_position', 'value')
    
    def __init__(self, position, value):
        self.store_position = position
        self.value = value

    def __str__(self):
        return f"CacheData(position: {self.store_position}, value: {self.value})"

    __repr__ = __str__

class Cog:

    def __init__(self, shared_cache=None, flush_interval=1, config=None):
        self.logger = logging.getLogger(__name__)
        self.config = config if config is not None else CogConfig()
        self.flush_interval = flush_interval
        self.logger.info(f"Cog init (flush_interval={flush_interval})")
        self.namespaces = {}
        self.current_table = None
        self.shared_cache = shared_cache
        self.cache = OrderedDict()
        '''creates Cog instance files.'''
        if os.path.exists(self.config.cog_instance_sys_file()):
            f = open(self.config.cog_instance_sys_file(), "rb")
            self.m_info = pickle.load(f)
            self.instance_id = self.m_info["m_instance_id"]
            f.close()
        else:
            self.instance_id = self.init_instance(self.config.COG_DEFAULT_NAMESPACE)

        '''Create default namespace and table.'''
        self.create_or_load_namespace(self.config.COG_DEFAULT_NAMESPACE)

        '''Load all table names but lazy load actual tables on request.'''
        for name in self.list_tables():
            if name not in self.namespaces:
                self.namespaces[name] = None

    def init_instance(self, namespace):
        pass

    def create_or_load_namespace(self, namespace):
        if not os.path.exists(self.config.cog_data_dir(namespace)):
            os.mkdir(self.config.cog_data_dir(namespace))
            self.logger.info("Created new namespace: " + self.config.cog_data_dir(namespace))
            '''add namespace to dict'''
            self.namespaces[namespace] = {}
        else:
            self.logger.info("Using existing namespace: " + self.config.cog_data_dir(namespace))
            self.load_namespace(namespace)

        self.current_namespace = namespace

    def is_namespace(self, namespace):
        pass

    def create_table(self, table_name, namespace):
        pass

    def load_namespace(self, namespace):
        if namespace not in self.namespaces:
            self.namespaces[namespace] = {}
            for index_file_name in os.listdir(self.config.cog_data_dir(namespace)):
                table_names = set()
                if self.config.INDEX in index_file_name:
                    id = self.config.index_id(index_file_name)
                    table_name = self.config.get_table_name(index_file_name)
                    if table_name not in table_names:
                        table_names.add(table_name)
                        self.logger.info("loading index: id: {}, table name: {}".format(id, table_name))
                        self.load_table(table_name, namespace)
                        self.refresh_cache(table_name, namespace)
        self.current_namespace = namespace

    def load_table(self, name, namespace):
        if namespace not in self.namespaces:
            self.namespaces[namespace] = {}
        self.logger.debug("loading table: " + name)

        if name not in self.namespaces[namespace]:
            self.namespaces[namespace][name] = Table(name, namespace, self.instance_id, self.config,
                                                     shared_cache=self.shared_cache,
                                                     flush_interval=self.flush_interval)
            self.logger.debug("created new table: " + name)

        self.current_table = self.namespaces[namespace][name]
        self.logger.debug("SET table {} in namespace {}. ".format(name, namespace))

    def refresh_cache(self, name, namespace):
        self.current_table = self.namespaces[namespace][name]
        for r in self.scanner():
            pass

    def refresh_all(self):
        pass

    def print_cache_info(self):
        pass

    def begin_batch(self):
        pass

    def end_batch(self):
        pass

    def sync(self):
        """
        Force flush all pending writes to disk across all tables.
        Blocks until all flushes are complete.
        """
        for name, space in self.namespaces.items():
            if space is None:
                continue
            for table_name, table in space.items():
                if table:
                    table.sync()

    def close(self):
        for name, space in self.namespaces.items():
            if space is None:
                continue
            for name, table in space.items():
                self.logger.info("closing.. : " + table.table_meta.name)
                table.close()

    def list_tables(self):
        p = set(())
        self.logger.debug("LIST TABLES, current namespace: " + str(self.current_namespace))
        path = self.config.cog_data_dir(self.current_namespace)
        if not os.path.exists(path):
            return p
        files = [f for f in listdir(path) if isfile(join(path, f))]
        for f in files:
            p.add(f.split("-")[0])
        return list(p)

    def get_table(self, name, namespace=None):
        pass

    def use_namespace(self, namespace):
        self.current_namespace = namespace
        return self

    def use_table(self, name):
        '''
        :param name:
        :param namespace:
        :return:
        '''
        if name not in self.namespaces[self.current_namespace] or self.namespaces[self.current_namespace][name]:
            self.load_table(name, self.current_namespace)
        else:
            self.current_table = self.namespaces[self.current_namespace][name]

        return self

    def put(self, data):
        assert isinstance(data.key, (str, bytes)), "key must be str or bytes."
        position = self.current_table.store.save(data)
        self.current_table.indexer.put(data.key, position, self.current_table.store)

    def put_list(self, data):
        pass

    def put_set(self, data):
        """
        Add a value to a set. Deduplicates via in-memory cache.
        Optimized: Uses O(1) head lookup instead of O(n) value chain traversal.
        """
        assert isinstance(data.key, (str, bytes)), "key must be str or bytes."
        assert isinstance(data.value, str), "Only string type is supported."

        cache_key = (self.current_table.table_meta.name, data.key)

        if cache_key in self.cache:
            cache_data = self.cache[cache_key]
            if data.value in cache_data.value:
                return
            new_record = Record(data.key, data.value, value_type='l')
            new_record.set_value_link(cache_data.store_position)
            position = self.current_table.store.save(new_record)
            self.current_table.indexer.put(new_record.key, position, self.current_table.store)
            cache_data.value.add(data.value)
            cache_data.store_position = position
            self.cache.move_to_end(cache_key)
            return

        head_record, head_pos = self.current_table.indexer.get_head_only(data.key, self.current_table.store)
        
        if head_record is None:
            new_record = Record(data.key, data.value, value_type='l')
            position = self.current_table.store.save(new_record)
            self.current_table.indexer.put(new_record.key, position, self.current_table.store)
            self.cache[cache_key] = CacheData(position, {data.value})
        else:
            record = self.current_table.indexer.get(data.key, self.current_table.store)
            existing_values = set(record.value)  # set() works on both list and set
            if data.value not in existing_values:
                new_record = Record(data.key, data.value, value_type='l')
                new_record.set_value_link(head_pos)
                position = self.current_table.store.save(new_record)
                self.current_table.indexer.put(new_record.key, position, self.current_table.store)
                existing_values.add(data.value)
                self.cache[cache_key] = CacheData(position, existing_values)
            else:
                self.cache[cache_key] = CacheData(head_pos, existing_values)

        if len(self.cache) > self.config.LEVEL_2_CACHE_SIZE:
            self.cache.popitem(last=False)
        self.cache.move_to_end(cache_key)

    def get(self, key):
        """Retrieve the record for *key* from the current table.

        The returned record may be a shared cached object.  Callers must
        not mutate it; treat it as read-only.
        """
        if key in self.cache:
            return self.cache[key]
        return self.current_table.indexer.get(key, self.current_table.store)

    def scanner(self, table=None, scan_filter=None):
        scan_itr = self.current_table.indexer.scanner(self.current_table.store) if not table else table.indexer.scanner(
            table.store)
        for r in scan_itr:
            if scan_filter:
                yield scan_filter.process(r.key)
            else:
                yield r

    def delete(self, key):
        self.current_table.indexer.delete(key, self.current_table.store)
        cache_key = (self.current_table.table_meta.name, key)
        if cache_key in self.cache:
            del self.cache[cache_key]

    def delete_edge(self, vertex1, predicate, vertex2):
        """
        Deletes edge in both directions.
        :param vertex1:
        :param predicate:
        :param vertex2:
        :return:
        """
        predicate_hashed = hash_predicate(predicate)
        out_object = self.use_table(predicate_hashed).get(out_nodes(vertex1))

        if out_object:
            if out_object.value_type == 'l':
                other_values = []
                for v in out_object.value:
                    if v != vertex2:
                        other_values.append(v)

                self.use_table(predicate_hashed).delete(out_nodes(vertex1))
                for ov in other_values:
                    self.use_table(predicate_hashed).put_set(Record(out_nodes(vertex1), ov))
            else:
                self.use_table(predicate_hashed).delete(out_nodes(vertex1))

        in_object = self.use_table(predicate_hashed).get(in_nodes(vertex2))
        if in_object:
            if in_object.value_type == 'l':
                other_values = []
                for v in in_object.value:
                    if v != vertex1:
                        other_values.append(v)

                self.use_table(predicate_hashed).delete(in_nodes(vertex2))
                for ov in other_values:
                    self.use_table(predicate_hashed).put_set(Record(in_nodes(vertex2), ov))
            else:
                self.use_table(predicate_hashed).delete(in_nodes(vertex2))

    def put_node(self, vertex1, predicate, vertex2):
        """
         Graph method
        :param vertex1: string
        :param predicate:
        :param vertex2:
        :return:

        A - B
        A - C
        B - C
        B - D put_node
        C - D
        ======
        A => [B,C]
        B => [A,D]
        C => [A,B,D]
        D => [B]
        """
        predicate_hashed = hash_predicate(predicate)
        self.use_table(self.config.GRAPH_EDGE_SET_TABLE_NAME).put(Record(str(predicate_hashed), predicate))
        self.use_table(self.config.GRAPH_NODE_SET_TABLE_NAME).put(Record(vertex1, ""))
        self.use_table(self.config.GRAPH_NODE_SET_TABLE_NAME).put(Record(vertex2, ""))
        self.use_table(predicate_hashed).put_set(Record(out_nodes(vertex1), vertex2))
        self.use_table(predicate_hashed).put_set(Record(in_nodes(vertex2), vertex1))

    def put_new_edge(self, vertex1, predicate, vertex2):
        """
        Graph method
        :param vertex1: string
        :param predicate:
        :param vertex2:
        :return:
        """
        predicate_hashed = hash_predicate(predicate)
        self.use_table(self.config.GRAPH_EDGE_SET_TABLE_NAME).put(Record(str(predicate_hashed), predicate))
        self.use_table(self.config.GRAPH_NODE_SET_TABLE_NAME).put(Record(vertex1, ""))
        self.use_table(self.config.GRAPH_NODE_SET_TABLE_NAME).put(Record(vertex2, ""))
        self.use_table(predicate_hashed).put(Record(out_nodes(vertex1), vertex2))
        self.use_table(predicate_hashed).put(Record(in_nodes(vertex2), vertex1))

    def update_edge(self, vertex1, predicate, vertex2):
        """
        Replace all edges from vertex1 (for this predicate) with a single edge to vertex2.
        
        This is an internal method used by Graph.put(update=True). It:
        1. Removes all existing outgoing edges from vertex1
        2. Removes vertex1 from all old targets' incoming edge lists
        3. Creates a new edge from vertex1 to vertex2
        
        :param vertex1: source vertex
        :param predicate: edge predicate  
        :param vertex2: new target vertex (replaces all existing targets)
        :return:
        
        WARNING: Thread Safety
        This method is NOT atomic. The sequence of read-delete-reinsert operations
        on incoming edge lists is susceptible to race conditions in concurrent
        environments. If another thread adds an edge to the same target between
        the read and delete operations, that edge may be lost. For concurrent
        access, external synchronization (e.g., locking) is required.
        """
        predicate_hashed = hash_predicate(predicate)

        out_object = self.use_table(predicate_hashed).get(out_nodes(vertex1))
        if out_object:
            if out_object.value_type == 'l' or out_object.value_type == 'u':
                old_targets = list(out_object.value)
            else:
                old_targets = [out_object.value]
            
            self.use_table(predicate_hashed).delete(out_nodes(vertex1))
            
            for old_target in old_targets:
                in_object = self.use_table(predicate_hashed).get(in_nodes(old_target))
                if in_object:
                    if in_object.value_type == 'l' or in_object.value_type == 'u':
                        other_sources = [v for v in in_object.value if v != vertex1]
                        self.use_table(predicate_hashed).delete(in_nodes(old_target))
                        for src in other_sources:
                            self.use_table(predicate_hashed).put_set(Record(in_nodes(old_target), src))
                    else:
                        if in_object.value == vertex1:
                            self.use_table(predicate_hashed).delete(in_nodes(old_target))

        self.put_node(vertex1, predicate, vertex2)

    def load_triples(self, graph_data_path, graph_name):
        pass

    def load_edgelist(self, edgelist_file_path, graph_name, predicate="none"):
        pass

    def load_csv(self, file_name, id_column_name, graph_name):
        pass
