"""泛型缓存工具，支持任意类型的对象缓存。"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Generic, TypeVar, Callable, Iterable

K = TypeVar("K")
V = TypeVar("V")

_DEFAULT_TTL_SECONDS = 300  # 5 分钟
_DEFAULT_MAX_SIZE = 1000


class CacheStore(Generic[K, V]):
    """泛型缓存存储，支持单对象和批量操作。

    线程安全：所有操作通过 threading.Lock 保护。
    TTL：缓存项在 ttl_seconds 后自动过期。
    容量上限：达到 max_size 时淘汰最近最少使用（LRU）条目，get/set 命中均刷新热度，
              OrderedDict 保证 O(1) 淘汰（替代旧的按写入时间 min() 全扫）。

    使用示例：
        # 简单缓存（key 为 int，value 为任意对象）
        agent_cache = CacheStore[int, GtAgent]()
        agent_cache.set(agent.id, agent)
        agent = agent_cache.get(agent_id)

        # 使用 key_extractor 自动提取 key
        agent_cache = CacheStore[int, GtAgent](key_extractor=lambda a: a.id)
        agent_cache.add(agent)  # 自动用 agent.id 作为 key
        agent_cache.add_many([agent1, agent2])
    """

    def __init__(
        self,
        key_extractor: Callable[[V], K] | None = None,
        *,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
        max_size: int = _DEFAULT_MAX_SIZE,
    ) -> None:
        """初始化缓存存储。

        Args:
            key_extractor: 可选的 key 提取函数，用于 add/add_many 方法自动提取 key。
                           若不提供，则必须显式调用 set/set_many 并传入 key。
            ttl_seconds: 缓存项存活时间（秒）。<=0 表示永不过期。
            max_size: 缓存最大条目数，超出时淘汰最近最少使用条目。
        """
        self._store: OrderedDict[K, V] = OrderedDict()
        self._timestamps: dict[K, float] = {}
        self._key_extractor = key_extractor
        self._ttl_seconds = ttl_seconds
        self._max_size = max_size
        self._lock = threading.Lock()

    def set(self, key: K, value: V) -> None:
        """设置单个缓存项。"""
        with self._lock:
            self._evict_if_needed()
            self._store[key] = value
            self._store.move_to_end(key)
            self._timestamps[key] = time.monotonic()

    def get(self, key: K) -> V | None:
        """获取单个缓存项，不存在或已过期时返回 None。"""
        with self._lock:
            if key not in self._store:
                return None
            if self._is_expired(key):
                self._store.pop(key, None)
                self._timestamps.pop(key, None)
                return None
            self._store.move_to_end(key)
            return self._store[key]

    def contains(self, key: K) -> bool:
        """检查 key 是否在缓存中（且未过期）。"""
        with self._lock:
            if key not in self._store:
                return False
            if self._is_expired(key):
                self._store.pop(key, None)
                self._timestamps.pop(key, None)
                return False
            return True

    def invalidate(self, key: K) -> None:
        """失效单个缓存项。"""
        with self._lock:
            self._store.pop(key, None)
            self._timestamps.pop(key, None)

    def clear(self) -> None:
        """清空所有缓存。"""
        with self._lock:
            self._store.clear()
            self._timestamps.clear()

    def set_many(self, items: dict[K, V]) -> None:
        """批量设置缓存项。"""
        with self._lock:
            now = time.monotonic()
            for key, value in items.items():
                self._evict_if_needed()
                self._store[key] = value
                self._store.move_to_end(key)
                self._timestamps[key] = now

    def get_many(self, keys: Iterable[K]) -> dict[K, V]:
        """批量获取缓存项，返回存在的项（自动跳过过期项）。"""
        with self._lock:
            result: dict[K, V] = {}
            for k in keys:
                if k in self._store and not self._is_expired(k):
                    self._store.move_to_end(k)
                    result[k] = self._store[k]
                elif k in self._store:
                    self._store.pop(k, None)
                    self._timestamps.pop(k, None)
            return result

    def add(self, value: V) -> None:
        """添加单个对象到缓存（使用 key_extractor 提取 key）。

        Raises:
            ValueError: 若未配置 key_extractor。
        """
        if self._key_extractor is None:
            raise ValueError("key_extractor is required for add() method")
        key = self._key_extractor(value)
        self.set(key, value)

    def add_many(self, values: Iterable[V]) -> None:
        """批量添加对象到缓存（使用 key_extractor 提取 key）。

        Raises:
            ValueError: 若未配置 key_extractor。
        """
        if self._key_extractor is None:
            raise ValueError("key_extractor is required for add_many() method")
        with self._lock:
            now = time.monotonic()
            for value in values:
                key = self._key_extractor(value)
                self._evict_if_needed()
                self._store[key] = value
                self._store.move_to_end(key)
                self._timestamps[key] = now

    def size(self) -> int:
        """返回缓存项数量。"""
        with self._lock:
            return len(self._store)

    def _is_expired(self, key: K) -> bool:
        """检查缓存项是否已过期（调用方须持有锁）。"""
        if self._ttl_seconds <= 0:
            return False
        ts = self._timestamps.get(key)
        if ts is None:
            return False
        return (time.monotonic() - ts) > self._ttl_seconds

    def _evict_if_needed(self) -> None:
        """达到容量上限时淘汰最近最少使用条目（调用方须持有锁，O(1)）。"""
        while len(self._store) >= self._max_size:
            evicted_key, _ = self._store.popitem(last=False)
            self._timestamps.pop(evicted_key, None)
