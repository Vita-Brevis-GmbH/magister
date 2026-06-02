import time

from magister_api.cache.ttl import TtlCache, bump_kind, cache_key_for_scope


def test_set_get_hit() -> None:
    c = TtlCache()
    c.set("k1", "v1", ttl_s=10.0)
    assert c.get("k1") == "v1"


def test_get_miss_after_ttl() -> None:
    c = TtlCache()
    c.set("k1", "v1", ttl_s=0.01)
    time.sleep(0.02)
    assert c.get("k1") is None


def test_lru_eviction() -> None:
    c = TtlCache(max_entries=2)
    c.set("a", 1, ttl_s=10.0)
    c.set("b", 2, ttl_s=10.0)
    c.set("c", 3, ttl_s=10.0)
    assert c.get("a") is None
    assert c.get("b") == 2
    assert c.get("c") == 3


def test_version_bump_changes_key() -> None:
    k1 = cache_key_for_scope("classes_active", (1, 2))
    bump_kind("classes_active")
    k2 = cache_key_for_scope("classes_active", (1, 2))
    assert k1 != k2


def test_scope_signature_is_order_stable() -> None:
    k1 = cache_key_for_scope("classes_active", (1, 2, 3))
    k2 = cache_key_for_scope("classes_active", (3, 1, 2))
    assert k1 == k2


def test_admin_scope_keyed_as_all() -> None:
    k = cache_key_for_scope("classes_active", None)
    assert k.endswith(":all")
