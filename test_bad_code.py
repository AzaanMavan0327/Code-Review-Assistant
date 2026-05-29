import os
import sys

api_key = "sk-1234567890abcdef"

def bad_function(items=[]):
    try:
        result = eval("1 + 1")
    except:
        pass
    return result
