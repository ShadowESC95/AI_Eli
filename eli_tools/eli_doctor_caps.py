#!/usr/bin/env python3
from __future__ import annotations
import json, sys
def main() -> int:
    try:
        from eli_tools.capabilities import as_text, as_jsonable, capability_names, capability_names_list
        print("OK: capabilities exports")
        print("as_text exists:", callable(as_text))
        print("as_jsonable exists:", callable(as_jsonable))
        print("capability_names_list type:", type(capability_names_list))
        print("capability_names() sample:", capability_names()[:10])
    except Exception as e:
        print("FAIL: capabilities:", repr(e))
        return 2

    try:
        from eli_tools.capability_registry import list_capabilities
        caps = list_capabilities()
        print("OK: registry list_capabilities:", len(caps))
    except Exception as e:
        print("FAIL: capability_registry:", repr(e))
        return 3
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
