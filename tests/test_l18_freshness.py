from harrowgate.freshness import AnswerCache, ChangeFeed, VersionedCache


def test_change_event_evicts_an_entry_inside_the_time_limit():
    feed, cache = ChangeFeed(), VersionedCache(ttl=5)
    cache.put("retail", "orders", "WG-1", {"status": "delivered"}, now=100)
    feed.publish("orders", "WG-1", at=101)
    assert cache.get("retail", "orders", "WG-1", now=102) is not None  # time limit alone: still served
    assert cache.get("retail", "orders", "WG-1", now=102, feed=feed) is None
    assert cache.evictions == 1


def test_time_limit_still_applies_and_none_means_events_only():
    cache = VersionedCache(ttl=5)
    cache.put("a", "t", "k", {}, now=0)
    assert cache.get("a", "t", "k", now=6) is None
    assert cache.get("a", "t", "k", now=600, ttl=None) is not None


def test_events_for_other_records_or_before_caching_do_not_evict():
    feed, cache = ChangeFeed(), VersionedCache(ttl=5)
    feed.publish("orders", "WG-1", at=90)
    cache.put("a", "orders", "WG-1", {}, now=100)
    feed.publish("orders", "WG-2", at=101)
    assert cache.get("a", "orders", "WG-1", now=102, feed=feed) is not None
    assert cache.cursor == feed.head == 2


def test_events_off_means_no_eviction():
    feed, cache = ChangeFeed(), VersionedCache(ttl=5, use_events=False)
    cache.put("a", "orders", "WG-1", {}, now=100)
    feed.publish("orders", "WG-1", at=101)
    assert cache.get("a", "orders", "WG-1", now=102, feed=feed) is not None


def test_answer_cache_is_keyed_by_document_version_and_tenant():
    c = AnswerCache()
    c.put("retail", "How long  do I have?", "RD-1", 1, "30 days")
    assert c.get("retail", "how long do i have?", "RD-1", 1) == "30 days"
    assert c.get("retail", "how long do i have?", "RD-1", 2) is None
    assert c.get("banking", "how long do i have?", "RD-1", 1) is None
    assert (c.hits, c.misses) == (1, 2)
