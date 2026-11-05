"""Thin wrapper around the Anthropic SDK for document extraction.

- PDFs go in as base64 `document` blocks (Claude reads each page as text + image, so scanned statements work).
- The documents are the first, stable part of the prompt and carry `cache_control`, so the classification call and
  the per-document extraction calls reuse the cached prefix.
- Output is constrained with `output_config.format` (JSON schema derived from our Pydantic models) and then
  validated with Pydantic; one repair retry on validation failure.
- Server-side refusal fallback (`fallbacks: "default"`) is enabled; set UNDERWRITER_FALLBACKS=0 to disable.
"""
from __future__ import annotations

import base64
import copy
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = os.environ.get("UNDERWRITER_MODEL", "claude-opus-5-5")
DEFAULT_EFFORT = os.environ.get("UNDERWRITER_EFFORT", "high")
USE_FALLBACKS = os.environ.get("UNDERWRITER_FALLBACKS", "1") != "0"


class LLMUnavailable(RuntimeError):
    pass


@dataclass
class DocInput:
    name: str
    data: bytes
    media_type: str = "application/pdf"


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    calls: int = 0
    log: list[str] = field(default_factory=list)

    def add(self, u, label: str):
        if u is None:
            return
        self.calls += 1
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            setattr(self, k, getattr(self, k) + (getattr(u, k, 0) or 0))
        self.log.append(f"{label}: in={getattr(u, 'input_tokens', 0)} out={getattr(u, 'output_tokens', 0)} "
                        f"cache_read={getattr(u, 'cache_read_input_tokens', 0) or 0}")


def strict_json_schema(model: Type[BaseModel]) -> dict:
    """Pydantic JSON schema -> structured-output friendly schema (all properties required, no extras, no defaults)."""
    schema = copy.deepcopy(model.model_json_schema())

    def walk(node):
        if isinstance(node, dict):
            if not isinstance(node.get("default"), dict):
                node.pop("default", None)
            if isinstance(node.get("title"), str):   # metadata only; never a property literally named "title"
                node.pop("title", None)
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            for v in list(node.values()):
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    return schema


def api_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


class ClaudeExtractor:
    def __init__(self, client=None, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT):
        if client is None:
            if not api_available():
                raise LLMUnavailable("ANTHROPIC_API_KEY is not set. Set it in .env (see .env.example) or load a saved extraction.")
            import anthropic
            client = anthropic.Anthropic()
        self.client = client
        self.model = model
        self.effort = effort
        self.usage = Usage()

    def _content(self, docs: list[DocInput], instruction: str) -> list[dict]:
        blocks: list[dict] = []
        for i, d in enumerate(docs):
            blocks.append({"type": "text", "text": f"Document {i + 1}: {d.name}"})
            blocks.append({"type": "document", "title": d.name,
                           "source": {"type": "base64", "media_type": d.media_type,
                                      "data": base64.standard_b64encode(d.data).decode("ascii")}})
        if blocks:
            blocks[-1]["cache_control"] = {"type": "ephemeral"}
        blocks.append({"type": "text", "text": instruction})
        return blocks

    def _request(self, system: str, content: list[dict], schema: dict, max_tokens: int):
        kwargs = dict(model=self.model, max_tokens=max_tokens, system=system,
                      messages=[{"role": "user", "content": content}],
                      output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}})
        if USE_FALLBACKS:
            kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        try:
            with self.client.beta.messages.stream(**kwargs) as stream:
                return stream.get_final_message()
        except Exception as e:  # noqa: BLE001 - retry once without the fallback beta if the API rejects it
            import anthropic
            if USE_FALLBACKS and isinstance(e, anthropic.BadRequestError) and "fallback" in str(e).lower():
                kwargs.pop("betas", None)
                kwargs.pop("fallbacks", None)
                with self.client.beta.messages.stream(**kwargs) as stream:
                    return stream.get_final_message()
            raise

    def extract(self, docs: list[DocInput], system: str, instruction: str, out_model: Type[T],
                label: str, max_tokens: int = 64000) -> T:
        schema = strict_json_schema(out_model)
        content = self._content(docs, instruction)
        msg = self._request(system, content, schema, max_tokens)
        self.usage.add(getattr(msg, "usage", None), label)
        if getattr(msg, "stop_reason", None) == "refusal":
            raise RuntimeError(f"{label}: the model declined the request ({getattr(msg, 'stop_details', None)}).")
        if getattr(msg, "stop_reason", None) == "max_tokens":
            raise RuntimeError(f"{label}: output hit max_tokens; split the document or raise max_tokens.")
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        try:
            return out_model.model_validate_json(text)
        except ValidationError as err:
            log.warning("%s: validation failed, retrying once: %s", label, err)
            repair = content + [{"type": "text", "text": "Your previous JSON failed validation with these errors:\n"
                                 f"{err}\nReturn corrected JSON only."}]
            msg = self._request(system, repair, schema, max_tokens)
            self.usage.add(getattr(msg, "usage", None), label + " (repair)")
            text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
            return out_model.model_validate_json(text)
