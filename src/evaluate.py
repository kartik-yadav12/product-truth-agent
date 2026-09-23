"""Run the pipeline over dev rows and score predictions against ground truth."""

from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from pathlib import Path

from .data_loader import Dataset, normalise_value
from .pipeline import ProductTruthPipeline

log = logging.getLogger(__name__)


def score_row(dataset, row, predicted):
    """Compare predicted values against the labelled dev row.

    Only characteristics that apply to the row's module AND carry a non-empty
    ground-truth value are scored.
    """
    module = str(row.get("MODULE", "")).strip()
    results = {}

    for characteristic in dataset.taxonomy_for_module(module):
        column = characteristic["output_column"]
        if not column or column not in row:
            continue

        truth = str(row[column]).strip()
        if not truth:
            continue

        got = str(predicted.get(column, "")).strip()
        results[column] = {
            "expected": truth,
            "predicted": got,
            "correct": normalise_value(got) == normalise_value(truth),
        }

    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--web", action="store_true", help="enable web retrieval (slow)"
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="force the deterministic baseline agent (no LLM calls)",
    )
    parser.add_argument("--out", default="outputs/dev_predictions.jsonl")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(), format="%(levelname)s %(name)s: %(message)s"
    )

    dataset = Dataset()
    pipeline = ProductTruthPipeline(dataset=dataset, offline=args.offline)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = min(args.limit, len(dataset.dev))
    records = []
    per_characteristic = defaultdict(lambda: [0, 0])  # column -> [correct, scored]
    failures = 0

    for position, (index, row) in enumerate(dataset.dev.head(total).iterrows(), start=1):
        try:
            prediction, _ = pipeline.run(row, do_web=args.web)
            scores = score_row(dataset, row, prediction["characteristics"])

            for column, result in scores.items():
                per_characteristic[column][1] += 1
                per_characteristic[column][0] += int(result["correct"])

            correct = sum(1 for r in scores.values() if r["correct"])
            records.append(
                {
                    "row": int(index),
                    "prediction": prediction,
                    "scores": scores,
                    "error": "",
                }
            )
            print(f"[{position}/{total}] row {index}: {correct}/{len(scores)} correct")
        except Exception as exc:  # noqa: BLE001 - one bad row must not stop the run
            failures += 1
            records.append({"row": int(index), "prediction": None, "scores": {}, "error": str(exc)})
            print(f"[{position}/{total}] row {index}: FAILED - {exc}")

    with out_path.open("w", encoding="utf8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    correct = sum(v[0] for v in per_characteristic.values())
    scored = sum(v[1] for v in per_characteristic.values())

    print(f"\nWrote {out_path}")
    print(f"Rows: {total}  failed: {failures}")
    if scored:
        print(f"Characteristic accuracy: {correct}/{scored} = {correct / scored:.1%}\n")
        for column, (hit, seen) in sorted(per_characteristic.items()):
            print(f"  {hit / seen:6.1%}  {hit:3d}/{seen:<3d}  {column}")
    else:
        print("No characteristics were scored.")


if __name__ == "__main__":
    main()
