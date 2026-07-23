import mmap
import struct
import os
import os.path
import time
import logging
import threading
import queue
from cog.store_cache import StoreCache
from cog.codec import (
    SpindleCodec,
    detect_codec,
)
from cog.config import INDEX_BLOCK_LEN as _DEFAULT_INDEX_BLOCK_LEN
import xxhash

_ZERO_BLOCK = b'\x00' * _DEFAULT_INDEX_BLOCK_LEN

_I64 = struct.Struct('<q')
_i64_pack = _I64.pack
_i64_unpack_from = _I64.unpack_from


class TableMeta:
    __slots__ = ('name', 'namespace', 'db_instance_id', 'column_mode')

    def __init__(self, name, namespace, db_instance_id, column_mode):
        self.name = name
        self.namespace = namespace
        self.db_instance_id = db_instance_id
        self.column_mode = column_mode


class Table:

    def __init__(self, name, namespace, db_instance_id, config, column_mode=False, shared_cache=None,
                 flush_interval=1):
        self.logger = logging.getLogger('cog.table')
        self.config = config
        self.shared_cache = shared_cache
        self.flush_interval = flush_interval
        self.table_meta = TableMeta(name, namespace, db_instance_id, column_mode)
        self.indexer = self.__create_indexer()
        self.store = self.__create_store(shared_cache)

    def __create_indexer(self):
        pass

    def __create_store(self, shared_cache):
        pass

    def sync(self):
        """Force flush pending writes to disk."""
        self.store.sync()

    def close(self):
        self.indexer.close()
        self.store.close()
        self.logger.info("closed table: " + self.table_meta.name)


class Record:
    __slots__ = ('key', 'value', 'timestamp',
                 'store_position', 'key_link', 'value_link', 'value_type')

    RECORD_LINK_NULL = -1
    VALUE_LINK_NULL = -1

    def __init__(self, key, value, store_position=None,
                 value_type="s", key_link=-1, value_link=-1, timestamp=None, **_ignored):
        self.key = key
        self.value = value
        self.store_position = store_position
        self.key_link = key_link
        self.value_link = value_link
        self.value_type = value_type
        self.timestamp = timestamp

    def set_store_position(self, pos):
        if type(pos) is not int:
            raise ValueError("store position must be int but provided : " + str(pos))
        self.store_position = pos

    def set_key_link(self, pos):
        pass

    def set_value_link(self, pos):
        self.value_link = pos

    def set_value(self, value):
        pass

    def is_equal_val(self, other_record):
        pass

    def get_kv_tuple(self):
        pass

    def marshal(self, codec=None):
        pass

    def is_empty(self):
        pass

    def __str__(self):
        return ("key: {}, value: {}, timestamp: {}, "
                "store_position: {}, key_link: {}, value_link: {}, value_type: {}").format(
            self.key, self.value, self.timestamp,
            self.store_position, self.key_link, self.value_link, self.value_type)

    @classmethod
    def unmarshal(cls, store_bytes, codec=None):
        pass

    @classmethod
    def __load_value(cls, store_pointer, val_list, store):
        """loads value from the store"""
        while store_pointer != Record.VALUE_LINK_NULL:
            rec = store.read(store_pointer)
            if rec.value_type == 'l':
                val_list.append(rec.value)
            else:
                val_list.add(rec.value)
            store_pointer = rec.value_link
        return val_list

    @classmethod
    def materialize_values(cls, record, store):
        """Return a new Record with the full value chain materialized for
        list/set types. The original record is not mutated (important when
        it lives in the store cache). No-op copy for scalars."""
        if record.value_type == 'l':
            full_value = cls.__load_value(record.value_link, [record.value], store)
        elif record.value_type == 'u':
            full_value = cls.__load_value(record.value_link, {record.value}, store)
        else:
            return record
        out = Record(record.key, full_value, store_position=record.store_position,
                     value_type=record.value_type, key_link=record.key_link,
                     value_link=record.value_link, timestamp=record.timestamp)
        return out

    @classmethod
    def load_from_store(cls, position: int, store):
        record = store.read(position)
        if record is None:
            return None
        return cls.materialize_values(record, store)


class Index:

    def __init__(self, table_meta, config, logger, index_id=0):
        self.logger = logging.getLogger('cog.index')
        self.table = table_meta
        self.config = config
        self.name = self.config.cog_index(table_meta.namespace, table_meta.name, table_meta.db_instance_id, index_id)

        self._block_len = config.INDEX_BLOCK_LEN
        self._capacity = config.INDEX_CAPACITY

        self.empty_block = _ZERO_BLOCK if self._block_len == _DEFAULT_INDEX_BLOCK_LEN else b'\x00' * self._block_len

        if not os.path.exists(self.name):
            self.logger.info("creating index...")
            total_size = self._block_len * self._capacity
            fd = os.open(self.name, os.O_RDWR | os.O_CREAT, 0o644)
            os.ftruncate(fd, total_size)
            os.close(fd)
            self.logger.info("new index with capacity" + str(self._capacity) + "created: " + self.name)
        else:
            self.logger.info("Index: "+self.name+" already exists.")

        self.db = open(self.name, 'r+b')
        self.db_mem = mmap.mmap(self.db.fileno(), 0)
        self._closed = False

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.db_mem.flush()
        self.db_mem.close()
        self.db.close()

    def get_index_key(self, int_store_position):
        pass

    def put(self, key, store_position, store):
        """
        key chain
        :param key:
        :param store_position:
        :param store:
        :return:
        """

        """
        k5 -> k4 -> k3 -> k2 -> k1
        add: k6
        k6 -> k5 -> k4 -> k3 -> k2 -> k1
        add/update: k4
        1. k4 -> k6 -> k5 -> k4 -> k3 -> k2 -> k1
        2. k4 -> k6 -> k5 -> k3 -> k2 -> k1

        """
        block_len = self._block_len
        db_mem = self.db_mem
        orig_position = self.get_index(key)
        head_pos = _i64_unpack_from(db_mem, orig_position)[0]
        if __debug__ and self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug('writing : %s current data at store position: %d', key, head_pos)
        if head_pos == 0:
            store.update_record_link_inplace(store_position, Record.RECORD_LINK_NULL)
            key_link = store_position
        else:
            existing_record = store.read(head_pos)

            if existing_record.key == key:
                store.update_record_link_inplace(store_position, existing_record.key_link)
                key_link = existing_record.key_link
            else:
                store.update_record_link_inplace(store_position, existing_record.store_position)
                key_link = existing_record.store_position

                prev_record = existing_record  # start with the head
                while existing_record.key_link != Record.RECORD_LINK_NULL:
                    next_pos = existing_record.key_link
                    existing_record = store.read(next_pos)
                    if existing_record.key == key:
                        """
                        if same key found in bucket, update previous record in chain to point to key_link of this record
                        prev_rec -> current rec.key_link
                        curr_rec will not be linked in the bucket anymore.
                        """
                        store.update_record_link_inplace(prev_record.store_position, existing_record.key_link)
                        key_link = existing_record.key_link
                    else:
                        prev_record = existing_record

        db_mem[orig_position: orig_position + block_len] = _i64_pack(store_position)
        return key_link

    def get_index(self, key):
        return self._block_len * cog_hash(key, self._capacity)

    def get(self, key, store):
        if __debug__ and self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug("GET: Reading index: %s", self.name)
        index_position = self.get_index(key)
        db_mem = self.db_mem
        store_pos = _i64_unpack_from(db_mem, index_position)[0]
        if store_pos == 0:
            return None
        record = store.read(store_pos)
        if __debug__ and self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug("read record %s", record)

        if record.key == key:
            return Record.materialize_values(record, store)
        while record.key_link != Record.RECORD_LINK_NULL:
            if __debug__ and self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug("record.key_link: %d", record.key_link)
            store_pos = record.key_link
            record = store.read(store_pos)
            if record.key == key:
                return Record.materialize_values(record, store)
        return None

    def get_head_only(self, key, store):
        """
        Get only the head record without traversing the value chain.
        This is O(1) compared to get() which is O(n) for multi-value keys.

        Returns: (record, store_position) or (None, None)
        """
        index_position = self.get_index(key)
        store_position = _i64_unpack_from(self.db_mem, index_position)[0]
        if store_position == 0:
            return None, None
        record = store.read(store_position)

        if record.key == key:
            return record, store_position
        else:
            while record.key_link != Record.RECORD_LINK_NULL:
                store_position = record.key_link
                record = store.read(store_position)
                if record.key == key:
                    return record, store_position
        return None, None

    '''
        Iterates through all records in the index, following key_link chains for hash collisions.
    '''

    def scanner(self, store):
        block_len = self._block_len
        db_mem = self.db_mem
        mem_len = len(db_mem)
        scan_cursor = 0
        while scan_cursor + block_len <= mem_len:
            store_position = _i64_unpack_from(db_mem, scan_cursor)[0]
            if store_position == 0:
                scan_cursor += block_len
                continue

            while store_position != Record.RECORD_LINK_NULL:
                record = Record.load_from_store(store_position, store)
                if record is None:  # EOF store
                    self.logger.error("Store EOF reached! Iteration terminated.")
                    return
                yield Record(record.key, record.value)
                store_position = record.key_link

            scan_cursor += block_len

    def delete(self, key, store):
        """
               k5 -> k4 -> k3 -> k2 -> k1
               del: k3
               k6 -> k5 -> k4 -> k2 -> k1

        """
        if __debug__ and self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug("DELETE: Reading index: %s", self.name)
        block_len = self._block_len
        db_mem = self.db_mem
        index_position = self.get_index(key)

        head_pos = _i64_unpack_from(db_mem, index_position)[0]
        if head_pos == 0:
            return False

        record = store.read(head_pos)
        if __debug__ and self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug("read record %s", record)
        if record.key == key:
            """delete bucket => map hash table to empty block, or point to next in chain"""
            if record.key_link != Record.RECORD_LINK_NULL:
                db_mem[index_position:index_position + block_len] = _i64_pack(record.key_link)
            else:
                db_mem[index_position:index_position + block_len] = self.empty_block
            return True
        else:
            """search bucket"""
            prev_record = record  # Initialize to the head record
            while record.key_link != Record.RECORD_LINK_NULL:
                next_pos = record.key_link
                next_record = store.read(next_pos)
                if next_record.key == key:
                    """
                    if same key found in bucket, update previous record in chain to point to key_link of this record
                    prev_rec -> current rec.key_link
                    curr_rec will not be linked in the bucket anymore.
                    """
                    store.update_record_link_inplace(prev_record.store_position, next_record.key_link)
                    return True
                prev_record = next_record
                record = next_record
        return False

    def flush(self):
        self.db_mem.flush()


class Store:

    def __init__(self, tablemeta, config, logger, caching_enabled=True, shared_cache=None,
                 flush_interval=1):
        self.caching_enabled = caching_enabled
        self.batch_mode = False  # When True, defers flush() until end_batch()
        self.logger = logging.getLogger('cog.store')
        self.tablemeta = tablemeta
        self.config = config
        self.flush_interval = flush_interval
        self.write_count = 0
        self._closed = False
        self._dirty = False

        self.store = self.config.cog_store(
            tablemeta.namespace, tablemeta.name, tablemeta.db_instance_id)
        self.store_cache = StoreCache(self.store, shared_cache)
        fd = os.open(self.store, os.O_RDWR | os.O_CREAT, 0o644)
        self.store_file = os.fdopen(fd, 'rb+')

        file_size = os.fstat(self.store_file.fileno()).st_size
        self.codec = detect_codec(self.store_file, file_size)
        if file_size == 0:
            self.codec.write_header(self.store_file)
            self.store_file.flush()
        self.created_at = self.codec.created_at
        self.data_start = self.codec.HEADER_SIZE

        self._lock = threading.Lock()

        self._mmap = None
        self._refresh_mmap()

        self._use_async = flush_interval > 1
        if self._use_async:
            self._flush_queue = queue.Queue()
            self._flush_thread = threading.Thread(target=self._flush_worker, daemon=True)
            self._flush_thread.start()
            self._shutdown = False

        logger.info(f"Store init: {self.store} (flush_interval={flush_interval}, codec=v{self.codec.VERSION})")

    def _refresh_mmap(self):
        try:
            size = os.fstat(self.store_file.fileno()).st_size
        except (OSError, ValueError):
            return
        if size <= self.data_start:
            return
        current = self._mmap
        if current is not None and len(current) >= size:
            return
        self._mmap = mmap.mmap(self.store_file.fileno(), 0,
                               access=mmap.ACCESS_READ)
        if current is not None:
            current.close()

    def _flush_worker(self):
        pass

    def _request_flush(self):
        """Request a flush - async if interval > 1, sync otherwise."""
        if self._closed:
            return
        if self._use_async:
            self._flush_queue.put("FLUSH")
        else:
            self.store_file.flush()
            self._dirty = False

    def _handle_write_flush(self):
        """Increment write count and trigger flush if threshold reached."""
        if not self.batch_mode:
            self.write_count += 1
            if self.flush_interval > 0 and self.write_count >= self.flush_interval:
                self._request_flush()
                self.write_count = 0

    def sync(self):
        """
        Force flush all pending writes to disk.
        Blocks until flush is complete.
        """
        if self._closed:
            return
        with self._lock:
            if not self._closed:
                self.store_file.flush()
                self._dirty = False
        if self._use_async:
            self._flush_queue.join()

    def close(self):
        """Close the store, ensuring all data is flushed."""
        if self._closed:
            return
            
        self._closed = True
        
        if self._use_async:
            self._shutdown = True
            self._flush_queue.put("SHUTDOWN")
            self._flush_thread.join(timeout=5.0)
        
        with self._lock:
            try:
                self.store_file.flush()
                self._dirty = False
                self._mmap = None
                self.store_file.close()
            except ValueError:
                pass  # File already closed

    def begin_batch(self):
        pass

    def end_batch(self):
        pass

    def save(self, record):
        """
        Store data with configurable flush behavior.
        """
        with self._lock:
            record.timestamp = time.time_ns()
            self.store_file.seek(0, 2)
            store_position = self.store_file.tell()
            record.set_store_position(store_position)
            marshalled_record = self.codec.encode_record(record)
            self.store_file.write(marshalled_record)
            self._dirty = True

            if self.caching_enabled:
                self.store_cache.put(store_position, record)

            self._handle_write_flush()

        return store_position

    def update_record_link_inplace(self, start_pos, int_value):
        """updates record link in store file in place"""
        if type(int_value) is not int:
            raise ValueError("store position must be int but provided : " + str(start_pos))

        byte_value = self.codec.key_link_bytes(int_value)
        if __debug__ and self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug('update_record_link_inplace: %s', byte_value)

        with self._lock:
            self.store_file.seek(start_pos)
            self.store_file.write(byte_value)
            self._dirty = True

            if self.caching_enabled:
                cached = self.store_cache.peek(start_pos)
                if cached is not None:
                    cached.key_link = int_value

            self._handle_write_flush()

    def read(self, position):
        """Read a record from the store at the given byte position.

        The returned record may be a shared cached object.  Callers must
        not mutate it; treat it as read-only.
        """
        if __debug__ and self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug("store read request at position: %d", position)
        if self.caching_enabled:
            cached_record = self.store_cache.get(position)
            if cached_record is not None:
                return cached_record

        if self._dirty:
            with self._lock:
                if self._dirty:
                    self.store_file.flush()
                    self._dirty = False
                    self._refresh_mmap()

        mm = self._mmap
        if mm is None or position + 17 > len(mm):
            self._refresh_mmap()
            mm = self._mmap
        if mm is not None and position + 17 <= len(mm):
            try:
                record, _ = self.codec.decode_at(mm, position)
            except (ValueError, KeyError, struct.error):
                pass
            else:
                record.store_position = position
                if self.caching_enabled:
                    with self._lock:
                        self.store_cache.put(position, record)
                return record

        with self._lock:
            self.store_file.seek(position)
            raw = self.codec.read_record(self.store_file)
        if raw is None:
            return None
        record = self.codec.decode_record(raw)
        record.store_position = position

        if self.caching_enabled:
            with self._lock:
                self.store_cache.put(position, record)

        return record


class Indexer:

    def __init__(self, tablemeta, config, logger):
        self.tablemeta = tablemeta
        self.config = config
        self.logger = logging.getLogger('cog.indexer')
        self.index_list = []  # future range index.
        self.index_id = 0
        self.load_indexes()
        if len(self.index_list) == 0:
            self.index_list.append(Index(tablemeta, self.config, logger, self.index_id))
            self.live_index = self.index_list[self.index_id]

    def close(self):
        for idx in self.index_list:
            idx.close()

    def load_indexes(self):
        pass

    def put(self, key, store_position, store):
        resp = self.live_index.put(key, store_position, store)
        if __debug__ and self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug("Key: %s indexed in: %s", key, self.live_index.name)
        return resp

    def get(self, key, store):
        for idx in self.index_list:
            result = idx.get(key, store)
            if result is not None:
                return result
        return None

    def get_head_only(self, key, store):
        """Get head record only, O(1) - doesn't traverse value chain."""
        for idx in self.index_list:
            record, pos = idx.get_head_only(key, store)
            if record is not None:
                return record, pos
        return None, None

    def scanner(self, store):
        for idx in self.index_list:
            if __debug__ and self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug("SCAN: index: %s", idx.name)
            for r in idx.scanner(store):
                yield r

    def delete(self, key, store):
        for idx in self.index_list:
            if idx.delete(key, store):
                return True
        return False

def cog_hash(string, index_capacity):
    return xxhash.xxh32(string, seed=2).intdigest() % index_capacity
