"""
Tests for the LLM response cache.

These tests use pytest's `tmp_path` fixture so each test gets its own
isolated cache directory. That keeps tests deterministic and prevents
them from polluting your real cache.
"""

from src.llm.cache import ResponseCache


def test_get_returns_none_on_miss(tmp_path):
    """A key that was never set should return None."""
    cache = ResponseCache(cache_dir=str(tmp_path / "cache"))

    assert cache.get("never-set-this-key") is None


def test_set_then_get_roundtrip(tmp_path):
    """Setting a value and retrieving it should return the same value."""
    cache = ResponseCache(cache_dir=str(tmp_path / "cache"))

    cache.set("key1", "some response string")
    assert cache.get("key1") == "some response string"


def test_make_key_is_deterministic(tmp_path):
    """Same inputs should always produce the same key."""
    cache = ResponseCache(cache_dir=str(tmp_path / "cache"))

    k1 = cache.make_key("findings A", "context B")
    k2 = cache.make_key("findings A", "context B")
    assert k1 == k2


def test_make_key_differs_for_different_inputs(tmp_path):
    """Different inputs should produce different keys."""
    cache = ResponseCache(cache_dir=str(tmp_path / "cache"))

    k1 = cache.make_key("findings A", "context B")
    k2 = cache.make_key("findings A", "context C")
    k3 = cache.make_key("findings X", "context B")

    # All three should be distinct.
    assert k1 != k2
    assert k1 != k3
    assert k2 != k3


def test_make_key_no_collision_on_concat_ambiguity(tmp_path):
    """
    Length-prefixing should prevent the ('AB', 'CD') vs ('A', 'BCD')
    collision that simple concatenation would cause.
    """
    cache = ResponseCache(cache_dir=str(tmp_path / "cache"))

    k1 = cache.make_key("AB", "CD")
    k2 = cache.make_key("A", "BCD")
    assert k1 != k2


def test_persistence_across_instances(tmp_path):
    """Values stored should be visible to a new instance using the same dir."""
    cache_dir = str(tmp_path / "cache")

    first = ResponseCache(cache_dir=cache_dir)
    first.set("persistent-key", "persistent-value")

    # New instance pointed at the same directory should see the value.
    second = ResponseCache(cache_dir=cache_dir)
    assert second.get("persistent-key") == "persistent-value"


def test_cache_dir_is_created_if_missing(tmp_path):
    """ResponseCache should create the directory if it doesn't exist yet."""
    cache_dir = tmp_path / "deeply" / "nested" / "cache"
    assert not cache_dir.exists()

    ResponseCache(cache_dir=str(cache_dir))
    assert cache_dir.exists()