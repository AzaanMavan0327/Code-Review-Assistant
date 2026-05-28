"""
Test fixture: a deliberately over-complex function.

This file exists ONLY to be analyzed by tests. The complexity here is
intentional, do not "fix" it.
"""


def process(status, value, items, retries, cleanup, logging, verbose):
    result = 0
    if status == "new":
        result = 1
    elif status == "active":
        result = 2
    if value > 100:
        result += value
    for item in items:
        if item < 0:
            result -= item
        elif item > 1000:
            result += item // 2
    while retries > 0:
        retries -= 1
    try:
        result = result / value
    except ZeroDivisionError:
        result = 0
    if cleanup:
        result = 0
    if logging and verbose:
        print(result)
    return result


def simple_function(x):
    """This one is fine, complexity = 1, should NOT trigger a finding."""
    return x + 1