"""
Tests for the unused imports check.
"""

from src.analyzer.analyzer import CodeAnalyzer


def test_unused_import_is_flagged():
    """A module imported but never used should be flagged."""
    source = """
import os
"""
    findings = CodeAnalyzer().analyze_source(source)
    unused = [f for f in findings if f.rule_id == "unused-import"]
    assert len(unused) == 1
    assert "os" in unused[0].message


def test_used_import_is_not_flagged():
    """An import that's referenced should NOT be flagged."""
    source = """
import os
print(os.getcwd())
"""
    findings = CodeAnalyzer().analyze_source(source)
    unused = [f for f in findings if f.rule_id == "unused-import"]
    assert unused == []


def test_attribute_access_counts_as_use():
    """`os.path.join` should mark `os` as used."""
    source = """
import os
x = os.path.join("a", "b")
"""
    findings = CodeAnalyzer().analyze_source(source)
    unused = [f for f in findings if f.rule_id == "unused-import"]
    assert unused == []


def test_from_import_unused():
    """`from typing import List` where List is unused should be flagged."""
    source = """
from typing import List
"""
    findings = CodeAnalyzer().analyze_source(source)
    unused = [f for f in findings if f.rule_id == "unused-import"]
    assert len(unused) == 1
    assert "List" in unused[0].message


def test_from_import_used():
    """`from typing import List` where List is used should NOT be flagged."""
    source = """
from typing import List
def f() -> List[int]:
    return []
"""
    findings = CodeAnalyzer().analyze_source(source)
    unused = [f for f in findings if f.rule_id == "unused-import"]
    assert unused == []


def test_import_as_alias_unused():
    """`import numpy as np` where np is unused should be flagged."""
    source = """
import numpy as np
"""
    findings = CodeAnalyzer().analyze_source(source)
    unused = [f for f in findings if f.rule_id == "unused-import"]
    assert len(unused) == 1
    # Should report the alias name, not the original module name.
    assert "np" in unused[0].message


def test_import_as_alias_used():
    """`import numpy as np` where np IS used should NOT be flagged."""
    source = """
import numpy as np
x = np.array([1, 2, 3])
"""
    findings = CodeAnalyzer().analyze_source(source)
    unused = [f for f in findings if f.rule_id == "unused-import"]
    assert unused == []


def test_partial_from_import_use():
    """Only the unused names from a from-import should be flagged."""
    source = """
from typing import List, Dict
x: List[int] = []
"""
    findings = CodeAnalyzer().analyze_source(source)
    unused = [f for f in findings if f.rule_id == "unused-import"]
    assert len(unused) == 1
    assert "Dict" in unused[0].message


def test_star_import_is_ignored():
    """`from x import *` should never be flagged (we can't tell)."""
    source = """
from os import *
"""
    findings = CodeAnalyzer().analyze_source(source)
    unused = [f for f in findings if f.rule_id == "unused-import"]
    assert unused == []