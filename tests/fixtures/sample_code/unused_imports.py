"""
Test fixture with unused import bugs.

Intentional issues for the analyzer to detect.
"""

import os                           # USED below
import sys                          # NEVER USED
import json                         # USED below
from typing import List, Dict, Set  # Only List is used

import numpy as np                  # NEVER USED


def process(items: List[int]) -> str:
    cwd = os.getcwd()
    data = json.dumps({"cwd": cwd, "items": items})
    return data