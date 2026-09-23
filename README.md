# Product Truth Agent — Complete Starter

This project implements a dataset-grounded pipeline for the Product Truth Agent challenge.

## Pipeline
1. Load challenge workbook and taxonomy/guidelines.
2. Identify a module (V1 requires it; QA module discovery is the next enhancement).
3. Search the web using barcode/brand/product description.
4. Retrieve candidate product pages and score evidence matches.
5. Ask the internal GPT-5.6 Luna endpoint to reason over only supplied evidence and rules.
6. Validate predictions against `char_value_list`.
7. Export the exact `sample_output` columns.

## Setup
```bash
cd product_truth_agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Put your actual Bearer API key in CIS_LLM_API_KEY
```

## Run UI
```bash
streamlit run app.py
```

## Test on dev
Without web retrieval:
```bash
python -m src.evaluate --limit 5
```
With web retrieval:
```bash
python -m src.evaluate --limit 5 --web
```
Then export:
```bash
python -c "from src.export import export_jsonl; print(export_jsonl())"
```

## Important
The challenge workbook is copied into `data/product_truth_agent_dataset.xlsx`. The web search fallback is intended for hackathon prototyping; for a production/hackathon submission with a permitted search provider, replace it with a licensed search API. Never commit the LLM API key.
