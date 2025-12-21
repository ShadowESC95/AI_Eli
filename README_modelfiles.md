# Multiple Ollama Modelfiles for XICHI-ANALYST

Build variants with identical guardrails but different base models:

```bash
./scripts/build_all_models.sh
```

Then choose per task:
```bash
python -m xichi_ai.llm_tasks derive-el --model xichi-analyst-qwen
python -m xichi_ai.llm_tasks normalize  --model xichi-analyst-llama
python -m xichi_ai.llm_tasks recovery   --model xichi-analyst-r1
python -m xichi_ai.llm_tasks weak       --model xichi-analyst-falcon
```
