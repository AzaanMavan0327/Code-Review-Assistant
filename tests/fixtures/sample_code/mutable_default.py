"""
Test fixture with mutable default argument bugs.

This file exists ONLY to be analyzed by tests. The bugs are intentional.
"""


def add_to_list(item, items=[]):
    """BUG: mutable default. The list is shared across calls."""
    items.append(item)
    return items


def add_to_dict(key, value, cache={}):
    """BUG: mutable default dict, same issue as the list version."""
    cache[key] = value
    return cache


def add_to_set(item, seen=set()):
    """BUG: constructor call returns a mutable, also shared across calls."""
    seen.add(item)
    return seen


def safe_default(item, items=None):
    """This one is correct, should NOT trigger a finding."""
    if items is None:
        items = []
    items.append(item)
    return items


def tuple_is_fine(values=(1, 2, 3)):
    """Tuples are immutable, safe as defaults. Should NOT trigger."""
    return values