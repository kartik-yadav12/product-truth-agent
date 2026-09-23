"""Deterministic, offline fallback agent.

Used when no LLM key is configured (`--offline`). It resolves each closed
characteristic by looking for its allowed values verbatim in the product
description and retrieved evidence, then falls back to the taxonomy's
"no claim" style default. This makes the whole pipeline runnable and testable
without network or credentials, and doubles as a baseline to score the LLM
against.
"""

from __future__ import annotations

import re

from .data_loader import normalise_value

# Ordered by preference: the first pattern that matches an allowed value wins.
DEFAULT_VALUE_PATTERNS = (
    "NO CLAIM",
    "NOT STATED",
    "NOT APPLICABLE",
    "NONE",
    "UNSPECIFIED",
)

# For binary WITH/WITHOUT style characteristics, absence of evidence means the
# claim was not made, so the negative form is the right default.
NEGATIVE_PREFIXES = ("WITHOUT ", "NO ", "NON ", "NON-", "NOT ")


def _haystack(product, evidence, max_chars=20000):
    parts = [
        str(product.get("RETAILER_DESC", "")),
        str(product.get("BRAND", "")),
    ]
    for item in sorted(evidence, key=lambda e: e.get("score", 0), reverse=True):
        parts.append(str(item.get("title", "")))
        parts.append(str(item.get("snippet", "")))
        parts.append(str(item.get("page_text", "")))
    return normalise_value(" ".join(parts))[:max_chars]


def _pick_default(possible_values, prior=None):
    """Choose a value when the evidence settles nothing.

    The module's most common labelled value is the strongest signal available,
    so it wins. Otherwise fall back to an explicit "no claim" value, then to the
    negative form of a with/without pair.
    """
    if prior:
        for value in possible_values:
            if normalise_value(value) == normalise_value(prior):
                return value

    for pattern in DEFAULT_VALUE_PATTERNS:
        for value in possible_values:
            if normalise_value(value) == pattern:
                return value

    for value in possible_values:
        if normalise_value(value).startswith(NEGATIVE_PREFIXES):
            return value

    return possible_values[0] if possible_values else ""


def _match_in_text(possible_values, text):
    """Longest verbatim word-boundary match wins (so 'MEDIUM SOFT' beats 'SOFT')."""
    best = None
    for value in possible_values:
        needle = normalise_value(value)
        if not needle:
            continue
        if re.search(rf"(?<![A-Z0-9]){re.escape(needle)}(?![A-Z0-9])", text):
            if best is None or len(needle) > len(normalise_value(best)):
                best = value
    return best


class BaselineAgent:
    name = "baseline"
    configured = True

    def __init__(self, dataset=None):
        # Optional; enables the "most common labelled value" prior.
        self.dataset = dataset

    def predict(self, product, taxonomy_context, evidence):
        text = _haystack(product, evidence)
        module = taxonomy_context["module"]
        priors = self.dataset.modal_values(module) if self.dataset else {}

        characteristics = {}
        matched = []

        for characteristic in taxonomy_context["characteristics"]:
            name = characteristic["characteristic"]
            values = characteristic["possible_values"]
            closed = str(characteristic["open_close"]).lower().startswith("close")

            if not closed:
                characteristics[name] = "NOT STATED"
                continue

            hit = _match_in_text(values, text)
            if hit:
                characteristics[name] = hit
                matched.append(f"{name}={hit}")
            else:
                characteristics[name] = _pick_default(
                    values, priors.get(characteristic.get("output_column"))
                )

        best_evidence = max(evidence, key=lambda e: e.get("score", 0), default=None)

        return {
            "module": taxonomy_context["module"],
            "characteristics": characteristics,
            "product_url": (best_evidence or {}).get("url", ""),
            "reasoning": (
                "Deterministic baseline: matched "
                f"{len(matched)}/{len(taxonomy_context['characteristics'])} "
                "characteristics verbatim in the product description and evidence "
                f"({'; '.join(matched) if matched else 'no verbatim matches'}); "
                "remaining characteristics defaulted from the taxonomy."
            ),
            "evidence": [
                {
                    "claim": f"Candidate product page (score {e.get('score')})",
                    "source_url": e.get("url", ""),
                    "support": "supported" if e.get("score", 0) >= 0.6 else "unclear",
                }
                for e in sorted(
                    evidence, key=lambda e: e.get("score", 0), reverse=True
                )[:4]
            ],
        }
