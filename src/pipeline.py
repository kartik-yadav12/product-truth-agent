"""End-to-end pipeline: evidence retrieval -> agent -> validation."""

from __future__ import annotations

import logging

from .baseline_agent import BaselineAgent
from .data_loader import Dataset
from .luna_agent import LunaAgent
from .retrieval import retrieve_product
from .validator import validate

log = logging.getLogger(__name__)


def build_agent(dataset, offline=False):
    if offline:
        return BaselineAgent(dataset)
    agent = LunaAgent()
    if not agent.configured:
        log.warning(
            "CIS_LLM_API_KEY is not set; falling back to the deterministic "
            "baseline agent. Set the key for full quality."
        )
        return BaselineAgent(dataset)
    return agent


class ProductTruthPipeline:
    def __init__(self, dataset=None, dataset_path=None, offline=False):
        if dataset is not None:
            self.ds = dataset
        else:
            self.ds = Dataset(dataset_path) if dataset_path else Dataset()
        self.agent = build_agent(self.ds, offline)

    def run(self, row, do_web=True):
        product = row.to_dict() if hasattr(row, "to_dict") else dict(row)

        module = str(product.get("MODULE", "")).strip()
        if not module:
            raise ValueError(
                "MODULE is required. The qa sheet ships without it, so supply one "
                "explicitly (module discovery is not implemented)."
            )

        context = self.ds.context(module)

        evidence = []
        if do_web:
            for candidate in retrieve_product(product):
                evidence.append(
                    {
                        "title": candidate.get("title"),
                        "url": candidate.get("url"),
                        "domain": candidate.get("domain"),
                        "snippet": candidate.get("snippet"),
                        "score": candidate.get("score"),
                        "page_text": candidate.get("page", {}).get("text", ""),
                    }
                )
            log.info(
                "Retrieved %d evidence page(s) for %s",
                len(evidence),
                product.get("RETAILER_DESC", "")[:60],
            )

        prediction = self.agent.predict(product, context, evidence)

        accepted, errors, warnings = validate(prediction, context, dataset=self.ds)
        if errors:
            log.warning("Validation dropped %d value(s): %s", len(errors), errors)

        prediction["characteristics"] = accepted
        prediction["validation_errors"] = errors
        prediction["validation_warnings"] = warnings
        prediction["agent"] = self.agent.name

        return prediction, evidence
