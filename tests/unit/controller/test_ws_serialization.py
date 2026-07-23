"""wsController._serialize_event 单元测试：广播序列化复用 + 紧凑 JSON。"""
from collections import OrderedDict

import service.messageBus as messageBus
from constants import MessageBusTopic
from controller import wsController


def _make_msg(topic=MessageBusTopic.ROOM_MSG_ADDED, event_id=1, payload=None):
    msg = messageBus.EventBusMessage(topic=topic, payload=payload or {"seq": 1, "content": "hi"})
    msg.event_id = event_id
    return msg


def _reset_cache():
    wsController._serialized_event_cache.clear()


def test_same_event_id_serialized_once_and_reused():
    _reset_cache()
    msg = _make_msg(event_id=100)
    first = wsController._serialize_event(msg)
    second = wsController._serialize_event(msg)
    assert first == second
    assert len(wsController._serialized_event_cache) == 1
    # payload 对所有连接相同，应含 event 名与 event_id
    assert '"event"' in first
    assert '"event_id"' in first and '100' in first


def test_compact_json_no_indent():
    """WS 广播使用紧凑 JSON（无缩进），减小帧体积。"""
    _reset_cache()
    msg = _make_msg(event_id=1, payload={"a": 1, "b": {"c": 2}})
    serialized = wsController._serialize_event(msg)
    assert "\n" not in serialized, "WS 序列化结果不应含换行（indent=None）"


def test_cache_is_bounded():
    _reset_cache()
    for i in range(wsController._SERIALIZED_EVENT_CACHE_MAX + 50):
        wsController._serialize_event(_make_msg(event_id=i))
    assert len(wsController._serialized_event_cache) == wsController._SERIALIZED_EVENT_CACHE_MAX
    # 最旧的应被淘汰，最新保留
    oldest = wsController._SERIALIZED_EVENT_CACHE_MAX + 49 - wsController._SERIALIZED_EVENT_CACHE_MAX
    assert oldest not in wsController._serialized_event_cache
    assert (wsController._SERIALIZED_EVENT_CACHE_MAX + 49) in wsController._serialized_event_cache


def test_two_events_independent_entries():
    _reset_cache()
    a = wsController._serialize_event(_make_msg(event_id=1, payload={"x": 1}))
    b = wsController._serialize_event(_make_msg(event_id=2, payload={"x": 2}))
    assert a != b
    assert set(wsController._serialized_event_cache.keys()) == {1, 2}
