"""Export predictions into the exact sample_output column layout."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .data_loader import Dataset


def export_predictions(
    path="outputs/dev_predictions.jsonl",
    out="outputs/predictions.xlsx",
    dataset=None,
):
    dataset = dataset or Dataset()

    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(
            f"{source} not found. Run `python -m src.evaluate` first."
        )

    records = []
    with source.open(encoding="utf8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue

            entry = json.loads(line)
            prediction = entry.get("prediction")
            if prediction is None:
                continue

            base = dataset.dev.iloc[entry["row"]].to_dict()
            base["PRODUCT_URL"] = prediction.get("product_url", "")
            base["REASONING"] = prediction.get("reasoning", "")
            base["MODULE"] = prediction.get("module") or base.get("MODULE", "")

            # `characteristics` is already keyed by exact output column name by
            # the validator, so these land in the right sample_output columns.
            for column, value in (prediction.get("characteristics") or {}).items():
                base[column] = value

            records.append(base)

    if not records:
        raise ValueError(f"No successful predictions found in {source}")

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    frame = pd.DataFrame(records).reindex(columns=dataset.output_columns).fillna("")
    frame.to_excel(out_path, index=False)
    return str(out_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default="outputs/dev_predictions.jsonl")
    parser.add_argument("--out", default="outputs/predictions.xlsx")
    args = parser.parse_args()
    print("Wrote", export_predictions(args.path, args.out))


if __name__ == "__main__":
    main()
