"""Loads the challenge workbook and exposes module taxonomy/guidelines/examples."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = PROJECT_ROOT / "data" / "product_truth_agent_dataset.xlsx"

# The `char_value_list` sheet names characteristics with spaces and slashes
# ("GLOBAL IF WITH FLUORIDE") while the dev/sample_output sheets use
# underscored column names ("GLOBAL_IF_WITH_FLUORIDE"). Normalising with
# `normalise_name` reconciles 12 of the 13 characteristics; the remaining one
# is not a mechanical transform and needs an explicit alias.
CHARACTERISTIC_COLUMN_ALIASES = {
    "GLOBAL_IF_WITH_INTERSPACE_CLAIM": "GLOBAL_INTERSPACE_CLAIM",
}


def normalise_name(value) -> str:
    """Upper-case and collapse every non-alphanumeric run into a single '_'."""
    return re.sub(r"[^A-Z0-9]+", "_", str(value or "").strip().upper()).strip("_")


def normalise_value(value) -> str:
    """Upper-case and collapse whitespace, preserving punctuation."""
    return re.sub(r"\s+", " ", str(value or "").strip()).upper()


class Dataset:
    REQUIRED_SHEETS = (
        "dev",
        "qa",
        "char_value_list",
        "char_guidelines",
        "sample_output",
        "dataset_understanding_guide",
    )

    def __init__(self, path=DEFAULT_DATASET):
        self.path = Path(path)

        if not self.path.exists():
            raise FileNotFoundError(
                f"Dataset workbook not found at {self.path}. "
                "Expected it at <project root>/data/product_truth_agent_dataset.xlsx"
            )

        with pd.ExcelFile(self.path) as book:
            missing = [s for s in self.REQUIRED_SHEETS if s not in book.sheet_names]
            if missing:
                raise ValueError(
                    f"Workbook {self.path.name} is missing sheet(s): {missing}. "
                    f"Found: {book.sheet_names}"
                )

            self.dev = pd.read_excel(book, sheet_name="dev").fillna("")
            self.qa = pd.read_excel(book, sheet_name="qa").fillna("")
            self.values = pd.read_excel(book, sheet_name="char_value_list").fillna("")
            self.guidelines = pd.read_excel(book, sheet_name="char_guidelines").fillna("")
            self.sample = pd.read_excel(book, sheet_name="sample_output").fillna("")
            self.guide = pd.read_excel(
                book, sheet_name="dataset_understanding_guide"
            ).fillna("")

        self.output_columns = list(self.sample.columns)

        # normalised output column -> exact output column
        self._column_index = {normalise_name(c): c for c in self.output_columns}

    # ------------------------------------------------------------------
    # name resolution
    # ------------------------------------------------------------------

    def output_column_for(self, characteristic) -> str | None:
        """Map a taxonomy characteristic (or model-emitted key) to its output column."""
        key = normalise_name(characteristic)
        key = CHARACTERISTIC_COLUMN_ALIASES.get(key, key)
        return self._column_index.get(key)

    # ------------------------------------------------------------------
    # workbook accessors
    # ------------------------------------------------------------------

    @staticmethod
    def parse_values(raw):
        """`possible_values` is a stringified Python list; fall back to '|' split."""
        if isinstance(raw, list):
            return [str(v).strip() for v in raw]
        try:
            parsed = ast.literal_eval(str(raw))
        except (ValueError, SyntaxError):
            parsed = None
        if isinstance(parsed, (list, tuple)):
            return [str(v).strip() for v in parsed]
        return [v.strip() for v in str(raw).split("|") if v.strip()]

    def modules(self):
        return sorted(
            {
                m
                for m in self.values["module"].astype(str).str.strip()
                if m and m.lower() != "nan"
            }
        )

    def taxonomy_for_module(self, module):
        rows = self.values[
            self.values["module"].astype(str).str.strip() == str(module).strip()
        ]
        out = []
        for _, r in rows.iterrows():
            characteristic = str(r["characteristic"]).strip()
            out.append(
                {
                    "characteristic": characteristic,
                    "output_column": self.output_column_for(characteristic),
                    "open_close": str(r["open_close"]).strip(),
                    "binary": str(r["binary"]).strip(),
                    "possible_values": self.parse_values(r["possible_values"]),
                    "notes": str(r["Notes"]).strip(),
                }
            )
        return out

    def guidelines_for_module(self, module):
        rows = self.guidelines[
            self.guidelines["MODULE NAME"].astype(str).str.strip()
            == str(module).strip()
        ]
        return [
            {
                "characteristic": str(r["CHARACTERISTICS NAME"]).strip(),
                "guideline": str(r["Guidelines"]).strip(),
            }
            for _, r in rows.iterrows()
        ]

    def module_examples(self, module, n=4):
        """Labelled dev rows for the module, trimmed to identity + its characteristics."""
        rows = self.dev[
            self.dev["MODULE"].astype(str).str.strip() == str(module).strip()
        ].head(n)

        keep = ["RETAILER_DESC", "BRAND", "EXTERNAL_CODE"]
        keep += [
            c["output_column"]
            for c in self.taxonomy_for_module(module)
            if c["output_column"]
        ]

        examples = []
        for _, r in rows.iterrows():
            examples.append(
                {k: str(r[k]) for k in keep if k in rows.columns and str(r[k]).strip()}
            )
        return examples

    def modal_values(self, module):
        """Most frequent labelled dev value per characteristic for this module.

        Used as a data-grounded prior when nothing in the evidence settles a
        characteristic, which beats picking an arbitrary allowed value.
        """
        rows = self.dev[
            self.dev["MODULE"].astype(str).str.strip() == str(module).strip()
        ]
        priors = {}
        if rows.empty:
            return priors

        for characteristic in self.taxonomy_for_module(module):
            column = characteristic["output_column"]
            if not column or column not in rows.columns:
                continue
            series = rows[column].astype(str).str.strip()
            series = series[series != ""]
            if not series.empty:
                priors[column] = series.mode().iloc[0]
        return priors

    def context(self, module, examples=4):
        characteristics = self.taxonomy_for_module(module)
        if not characteristics:
            raise ValueError(
                f"Module {module!r} has no characteristics in char_value_list. "
                f"Known modules: {len(self.modules())}"
            )
        return {
            "module": module,
            "characteristics": characteristics,
            "guidelines": self.guidelines_for_module(module),
            "examples": self.module_examples(module, examples),
        }
