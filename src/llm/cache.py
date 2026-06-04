"""
Cache for LLM API responses.

Caching saves money during development (no double-spending on the same
finding) and makes tests deterministic. We cache at the level of the raw
API response (a JSON string) rather than the parsed EnrichedFinding
objects. Caching strings is simpler than caching dataclasses, and if we
later change EnrichedFinding's shape, old cache entries remain valid
because they get re-parsed fresh on every read.

The cache is content-addressed: the key is a SHA-256 hash of the inputs
(findings JSON + code context). Identical inputs always produce the same
key, so we get cache hits across runs without any explicit invalidation.
"""

import hashlib
from pathlib import Path
from typing import Optional

from diskcache import Cache


# Default cache location. Listed in .gitignore so it never gets committed.
_DEFAULT_CACHE_DIR = ".cache/llm"


class ResponseCache:
    """
    Disk-backed cache for raw LLM API response strings.

    Usage:
        cache = ResponseCache()
        key = cache.make_key(findings_json, code_context)
        cached = cache.get(key)
        if cached is None:
            response = call_api(...)
            cache.set(key, response)
            return response
        return cached
    """

    def __init__(self, cache_dir: str = _DEFAULT_CACHE_DIR) -> None:
        """
        Args:
            cache_dir: Directory where cache files are stored. Tests can
                pass a tmp_path to keep test runs isolated from your
                real cache.
        """
        # Ensure the directory exists; diskcache fails if the parent
        # doesn't already exist.
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        self._cache = Cache(cache_dir)

    def get(self, key: str) -> Optional[str]:
        """
        Retrieve a cached value, or None if not found.

        Returns None on a miss rather than raising, which keeps call sites
        clean (no try/except needed for the common case).
        """
        value = self._cache.get(key)
        # diskcache can technically store non-strings too. We only ever
        # store strings, but the isinstance check protects against
        # corrupted cache files.
        return value if isinstance(value, str) else None

    def set(self, key: str, value: str) -> None:
        """Store a value under the given key."""
        self._cache.set(key, value)

    def make_key(self, findings_json: str, code_context: str) -> str:
        """
        Build a stable hash key from the LLM inputs.

        Length-prefixing each component guarantees that different input
        pairs can never produce the same hash, even in pathological
        cases. Without it, ("AB", "CD") and ("A", "BCD") would collide
        after concatenation.
        """
        h = hashlib.sha256()
        f_bytes = findings_json.encode("utf-8")
        c_bytes = code_context.encode("utf-8")
        h.update(len(f_bytes).to_bytes(8, "big"))
        h.update(f_bytes)
        h.update(len(c_bytes).to_bytes(8, "big"))
        h.update(c_bytes)
        return h.hexdigest()