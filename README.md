# Product Truth Agent

Dataset-grounded pipeline that identifies a retail product, gathers evidence for
it, and codes it against the Haleon oral-care characteristic taxonomy.

## Pipeline

1. Load the challenge workbook (taxonomy, guidelines, labelled dev rows).
2. Resolve the product's module (required; module discovery is not implemented).
3. Look the barcode up in public product APIs, then best-effort web search.
4. Fetch and score candidate pages against the barcode/brand/description.
5. Ask the agent to code each characteristic using only the supplied evidence.
6. Validate every value against the module's closed `char_value_list`.
7. Export into the exact `sample_output` column layout.

---

## Quick start

```bash
git clone https://github.com/shashankskkumar21/new-.git
cd new-

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then edit .env and set CIS_LLM_API_KEY
```

Verify the install without needing any credentials or network:

```bash
python -m src.evaluate --limit 20 --offline
```

Expected: `Rows: 20  failed: 0` and roughly 75% characteristic accuracy.

---

## How to run

### 1. Streamlit UI

```bash
./run.sh                    # creates .venv, installs deps, launches
# or, inside an activated venv:
streamlit run app.py
```

Opens on <http://localhost:8501>. Sidebar options:

| Control | Effect |
|---|---|
| **Mode** | `Development product` picks a labelled dev row; `Custom product` lets you type a barcode/brand/description. |
| **Web retrieval** | Off = classify from the product record alone. On = barcode APIs + web search. |
| **Offline baseline agent** | Skip the LLM entirely and use the deterministic agent. |

### 2. Score against the labelled dev rows

The `dev` sheet ships with ground-truth labels, so `evaluate` reports real
accuracy — overall and per characteristic.

```bash
python -m src.evaluate --limit 20              # LLM, no web retrieval
python -m src.evaluate --limit 20 --web        # LLM + evidence retrieval
python -m src.evaluate --limit 20 --offline    # deterministic baseline, no LLM
python -m src.evaluate --limit 5 --web --log-level DEBUG   # verbose
```

| Flag | Default | Meaning |
|---|---|---|
| `--limit N` | 10 | Number of dev rows to process. |
| `--web` | off | Enable barcode lookup + web search. Slower. |
| `--offline` | off | Force the baseline agent; makes no LLM calls. |
| `--out PATH` | `outputs/dev_predictions.jsonl` | Where predictions are written. |
| `--log-level` | `INFO` | `DEBUG` shows dropped pages and provider failures. |

Output looks like:

```
[1/20] row 0: 7/9 correct
...
Rows: 20  failed: 0
Characteristic accuracy: 82/109 = 75.2%

  100.0%    6/6    GLOBAL_CONSUMER_LIFESTAGE_CLAIM
   16.7%    1/6    GLOBAL_ORAL_CARE_FUNCTION
```

### 3. Export to the submission layout

```bash
python -m src.export
python -m src.export --path outputs/dev_predictions.jsonl --out outputs/predictions.xlsx
```

Writes `outputs/predictions.xlsx` with columns identical to the workbook's
`sample_output` sheet.

### 4. Classify a single custom product in Python

```python
from src.data_loader import Dataset
from src.pipeline import ProductTruthPipeline

dataset = Dataset()
pipeline = ProductTruthPipeline(dataset=dataset, offline=True)

prediction, evidence = pipeline.run(
    {
        "EXTERNAL_CODE": "5000347071614",
        "BRAND": "AQUAFRESH",
        "RETAILER_DESC": "aquafresh whitening pump 100ml",
        "MODULE": "TOOTH CLEANING - FOAM/GEL/LIQUID/PASTE (NATURAL TEETH)",
    },
    do_web=True,
)

print(prediction["characteristics"])   # keyed by exact output column name
print(prediction["validation_errors"])
```

---

## Configuration

All settings are read from `.env` (see `.env.example`). None are required for
`--offline` runs.

| Variable | Default | Purpose |
|---|---|---|
| `CIS_LLM_API_KEY` | – | Luna key. `Bearer ` prefix optional. Without it the pipeline falls back to the baseline agent. |
| `CIS_LLM_ENDPOINT` | Nielsen CIS host | Chat-completions base URL. |
| `CIS_LLM_MODEL` | `hack-fest-gpt-5.6-luna` | Model name. |
| `CIS_LLM_API_VERSION` | `2025-03-01-preview` | API version query parameter. |
| `TAVILY_API_KEY` | – | Licensed search provider. Strongly preferred over scraping. |
| `MAX_SEARCH_RESULTS` | `6` | Search results considered per query. |
| `MAX_PAGE_CHARS` | `18000` | Characters kept per fetched page. |
| `MIN_EVIDENCE_SCORE` | `0.35` | Pages below this relevance score are discarded. |
| `MAX_EVIDENCE_ITEMS` | `4` | Evidence pages sent to the LLM. |
| `MAX_EVIDENCE_CHARS` | `6000` | Characters of page text per evidence item. |
| `REQUEST_TIMEOUT` | `15` | HTTP timeout in seconds. |
| `REQUESTS_CA_BUNDLE` | – | Explicit CA bundle for TLS-intercepting networks. |
| `PTA_INSECURE_SSL` | – | `1` disables TLS verification. Prototyping only. |
| `PTA_CACHE_DIR` | `.cache/barcode` | Barcode lookup cache location. |

**Never commit `.env`.** It is gitignored.

---

## Agents

| Agent | When | Notes |
|---|---|---|
| `LunaAgent` | `CIS_LLM_API_KEY` is set | Internal GPT endpoint; reasons over the supplied evidence only. |
| `BaselineAgent` | `--offline`, or no key configured | Deterministic. Matches allowed values verbatim in the description/evidence, otherwise falls back to the module's most common labelled value. No network, no credentials. |

The baseline exists so the pipeline is runnable and testable without
credentials, and as a floor to measure the LLM against. It scores ~75%
characteristic accuracy on the first 40 dev rows. Web evidence barely moves
that number, because a verbatim matcher extracts little that `RETAILER_DESC`
does not already contain — exploiting a full product page is the LLM's job.

## Evidence sources

Ranked by trust:

1. **Barcode APIs** — UPCitemdb, Open Beauty Facts, Open Food Facts. Keyless,
   keyed on the exact EAN/UPC. Responses are cached under `.cache/barcode/`
   because the UPCitemdb trial tier allows ~100 lookups/day.
2. **Tavily** — used for search when `TAVILY_API_KEY` is set. This is the only
   search path suitable for anything beyond prototyping.
3. **Bing / DuckDuckGo scraping** — best effort only. Both actively degrade
   automated traffic: DuckDuckGo serves a CAPTCHA, and Bing returns *unrelated*
   results rather than an error (a barcode query can come back with Microsoft
   Word support pages). Results below `MIN_EVIDENCE_SCORE` are discarded rather
   than passed off as evidence. Do not rely on this path.

---

## Troubleshooting

### `CIS_LLM_API_KEY is not set`
No `.env`, or the key is blank. Either set it, or pass `--offline` to use the
deterministic agent.

### Luna requests time out / connection never establishes
The CIS endpoint resolves to a **private address on Nielsen's internal network**:

```
$ nslookup llm-api-cis.azure-intlsd-np.nielsencsp.net
Address: 10.249.224.116

$ curl --max-time 45 https://llm-api-cis.azure-intlsd-np.nielsencsp.net/v1/models
curl: (28) Connection timed out    # connect=0.000000s — TCP never opened
```

If `connect` is `0.000000s`, the handshake never started: this is **routing, not
TLS and not the key**. Confirm with `traceroute 10.249.224.116` — it will die at
your ISP/corporate edge. You must be on the Nielsen VPN. Nothing in this repo
can work around it.

### `CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain`
Your network intercepts TLS (Netskope, Zscaler, etc.). `requests` and the Azure
SDK use certifi's bundle, which does not contain your corporate root CA, even
though `curl` works because it uses the OS trust store.

`src/__init__.py` installs [`truststore`](https://pypi.org/project/truststore/)
at import time to use the OS trust store, which fixes this automatically. If it
still fails:

```bash
export REQUESTS_CA_BUNDLE=/path/to/corporate-ca-bundle.pem
# last resort, prototyping only:
export PTA_INSECURE_SSL=1
```

### Search returns nothing / irrelevant results
Expected. Run with `--log-level DEBUG` to see per-provider failures. Set
`TAVILY_API_KEY` for a reliable search path. Barcode lookups are unaffected.

### `No usable search results for query ...`
Both scrapers were blocked. The run continues using barcode evidence only.

### Barcode lookups stop returning data
UPCitemdb's keyless trial tier allows ~100 lookups/day. Cached responses under
`.cache/barcode/` do not count against it; delete that directory to force a
refetch.

### `FileNotFoundError: Dataset workbook not found`
`data/product_truth_agent_dataset.xlsx` is missing. It is committed to the repo,
so this usually means you are running from the wrong directory.

---

## Notes

- **Characteristic names do not match output column names.** `char_value_list`
  uses `GLOBAL IF WITH FLUORIDE`; the output sheets use
  `GLOBAL_IF_WITH_FLUORIDE`. `Dataset.output_column_for` reconciles them, with
  an explicit alias for `GLOBAL IF WITH INTERSPACE CLAIM` →
  `GLOBAL_INTERSPACE_CLAIM`, which is not a mechanical transform.
- **Closed-list violations are dropped, not exported.** They are reported in
  `validation_errors`.

## Layout

```
app.py                 Streamlit UI
src/__init__.py        .env loading + TLS trust configuration
src/data_loader.py     workbook access, name normalisation
src/retrieval.py       search providers, page fetch, scoring
src/barcode.py         keyless barcode product APIs
src/luna_agent.py      internal LLM client
src/baseline_agent.py  deterministic offline agent
src/validator.py       closed-list enforcement
src/pipeline.py        orchestration
src/evaluate.py        scoring against labelled dev rows
src/export.py          sample_output export
data/                  challenge workbook
outputs/               generated predictions (gitignored)
.cache/                barcode lookup cache (gitignored)
```
