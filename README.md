

## Robust LLM wrappers: batched harvest + validators

### Batched equation harvest (page-friendly chunks)
```bash
# After pdf -> text ingest:
python -m xichi_ai.cli ingest --pdf-dir data/input

# Use Ollama model with strict prompt, chunked by ~12k chars (tune as needed)
python -m xichi_ai.llm_batch harvest-batched --model xichi-analyst-qwen --pdf-txt-dir data/cache --out data/cache/equations_llm.json --max-chars 12000
```

### Validate outputs (auto-run in batcher, also callable directly)
- `equations_llm.json` is validated for schema (file, page_guess, eq_label?, latex).
- `symbols.yaml` validator expects alias → {canonical, notes?, units?}.

You can also import and call:
```python
from xichi_ai.validation.validator import validate_equations_json, validate_symbols_yaml
validate_equations_json("data/cache/equations_llm.json")
validate_symbols_yaml("data/cache/symbols.yaml")
```
Eli can also control pc interactions and act out commands such as, web searches, opening applications, creating documents and entering content in it's current form.
