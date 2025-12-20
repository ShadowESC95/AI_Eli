import json, yaml
from pathlib import Path

class ValidationError(Exception): pass

def _is_str(x): return isinstance(x, str) and x.strip()

def validate_equations_json(obj_or_path):
    """
    Accepts either:
      - a list[dict] already loaded, or
      - a str/Path to a JSON file containing the list.
    Returns the validated list.
    """
    # Load if a path-like was provided
    if isinstance(obj_or_path, (str, Path)):
        p = Path(obj_or_path)
        data = json.loads(p.read_text(encoding="utf-8"))
    else:
        data = obj_or_path

    if not isinstance(data, list):
        raise ValidationError("Top-level must be a list of objects.")

    for i, o in enumerate(data):
        if not isinstance(o, dict):
            raise ValidationError(f"Item {i} is not an object")
        if not _is_str(o.get("file")):
            raise ValidationError(f"Item {i}: missing/invalid 'file'")
        if not _is_str(o.get("latex")):
            raise ValidationError(f"Item {i}: missing/invalid 'latex'")
        pg = o.get("page_guess", None)
        if pg is not None and not isinstance(pg, int):
            raise ValidationError(f"Item {i}: 'page_guess' must be int or null")
        el = o.get("eq_label", None)
        if el is not None and not _is_str(el):
            raise ValidationError(f"Item {i}: 'eq_label' must be string or null")
    return data

def validate_symbols_yaml(path):
    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValidationError("Top-level YAML must be a mapping (aliases -> {...})")
    for alias, entry in data.items():
        if not _is_str(alias):
            raise ValidationError("alias must be string")
        if not isinstance(entry, dict):
            raise ValidationError(f"{alias}: entry must be a mapping")
        if not _is_str(entry.get("canonical")):
            raise ValidationError(f"{alias}: missing 'canonical'")
    return data
