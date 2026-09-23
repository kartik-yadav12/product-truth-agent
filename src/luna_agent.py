"""Client for the internal CIS/Luna chat-completions endpoint."""

from __future__ import annotations

import json
import os
import re

from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import AzureError


SYSTEM_PROMPT = """You are Product Truth Agent.

Rules:
- Use ONLY the supplied product record, the supplied evidence, and the supplied
  taxonomy/guidelines. Never invent facts.
- Answer every characteristic listed in taxonomy.characteristics.
- For a characteristic marked open_close="Close", the value MUST be copied
  verbatim from its possible_values list. No paraphrasing, no new values.
- If the evidence does not establish a value and the guideline defines a
  default, use that default. Otherwise pick the explicit "no claim" /
  "not stated" style value from possible_values when one exists.
- product_url must be the URL of the single best-matching evidence page, or ""
  if no evidence page matches the product.
- Return raw JSON only. No markdown, no code fences, no commentary."""

RESPONSE_SHAPE = """Return exactly this JSON shape:
{"module":"...",
 "characteristics":{"CHARACTERISTIC NAME":"VALUE"},
 "product_url":"...",
 "reasoning":"...",
 "evidence":[{"claim":"...","source_url":"...","support":"supported|not_supported|unclear"}]}"""


class LLMNotConfigured(RuntimeError):
    pass


def extract_json(raw: str) -> dict:
    """Parse a JSON object out of a model response, tolerating fences/prose."""
    text = (raw or "").strip()

    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Model returned non-JSON output: {raw[:1000]}")


def _trim_evidence(evidence, max_items, max_chars):
    """Keep the prompt bounded: best-scoring pages first, page text truncated."""
    ordered = sorted(evidence, key=lambda e: e.get("score", 0), reverse=True)
    trimmed = []
    for item in ordered[:max_items]:
        trimmed.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("snippet", ""),
                "score": item.get("score"),
                "page_text": (item.get("page_text") or "")[:max_chars],
            }
        )
    return trimmed


class LunaAgent:
    name = "luna"

    def __init__(self):
        self.endpoint = os.getenv(
            "CIS_LLM_ENDPOINT",
            "https://llm-api-cis.azure-intlsd-np.nielsencsp.net/",
        )
        self.model = os.getenv("CIS_LLM_MODEL", "hack-fest-gpt-5.6-luna")
        self.api_version = os.getenv("CIS_LLM_API_VERSION", "2025-03-01-preview")
        self.max_evidence = int(os.getenv("MAX_EVIDENCE_ITEMS", "4"))
        self.max_evidence_chars = int(os.getenv("MAX_EVIDENCE_CHARS", "6000"))

        # Accept the key with or without a "Bearer " prefix.
        raw_key = os.getenv("CIS_LLM_API_KEY", "").strip()
        self.token = re.sub(r"^bearer\s+", "", raw_key, flags=re.IGNORECASE).strip()

        self.client = (
            ChatCompletionsClient(
                endpoint=self.endpoint,
                credential=AzureKeyCredential(self.token),
                api_version=self.api_version,
            )
            if self.token
            else None
        )

    @property
    def configured(self) -> bool:
        return self.client is not None

    def predict(self, product, taxonomy_context, evidence):
        if not self.configured:
            raise LLMNotConfigured(
                "CIS_LLM_API_KEY is not set. Copy .env.example to .env and add your "
                "key, or run with --offline to use the deterministic baseline agent."
            )

        payload = {
            "product": product,
            "taxonomy": taxonomy_context,
            "evidence": _trim_evidence(
                evidence, self.max_evidence, self.max_evidence_chars
            ),
        }

        user = (
            f"{RESPONSE_SHAPE}\n\nINPUT:\n"
            f"{json.dumps(payload, ensure_ascii=False, default=str)}"
        )

        try:
            response = self.client.complete(
                messages=[
                    SystemMessage(content=SYSTEM_PROMPT),
                    UserMessage(content=user),
                ],
                model=self.model,
                temperature=0,
                # The gateway authenticates on Authorization; AzureKeyCredential
                # alone sends `api-key`, which it ignores.
                headers={"Authorization": f"Bearer {self.token}"},
            )
        except AzureError as exc:
            raise RuntimeError(f"Luna request failed: {exc}") from exc

        if not response.choices:
            raise RuntimeError("Luna returned no choices")

        return extract_json(response.choices[0].message.content)
