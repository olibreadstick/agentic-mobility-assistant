"""Minimal, dependency-free LLM clients (OpenAI, Google Gemini, Anthropic) and a mock.

API keys are read from the environment (OPENAI_API_KEY, GEMINI_API_KEY,
ANTHROPIC_API_KEY). Every call returns (parsed_json, meta) where meta records
latency, token usage when reported, and the raw text for auditing.
"""
from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.request
from typing import Any, Dict, Optional, Tuple


def _extract_json(text: str) -> Any:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise


def _post(url: str, payload: Dict, headers: Dict[str, str], timeout: float = 300.0) -> Dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={
        "Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


class Provider:
    name = "base"

    def __init__(self, model: str, temperature: Optional[float] = None, retries: int = 3):
        self.model = model
        self.temperature = temperature
        self.retries = retries

    def _call(self, prompt: str) -> Tuple[str, Dict]:
        raise NotImplementedError

    def complete_json(self, prompt: str) -> Tuple[Any, Dict]:
        last = None
        for k in range(self.retries):
            t0 = time.time()
            try:
                text, usage = self._call(prompt)
                meta = {"provider": self.name, "model": self.model, "latency_s": round(time.time() - t0, 3),
                        "usage": usage, "raw": text}
                return _extract_json(text), meta
            except Exception as e:  # network or parse error: retry with backoff
                last = e
                time.sleep(2 ** k)
        raise RuntimeError(f"{self.name}:{self.model} failed after {self.retries} attempts: {last}")


class OpenAIProvider(Provider):
    name = "openai"

    def _call(self, prompt):
        body = {"model": self.model, "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"}}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        r = _post("https://api.openai.com/v1/chat/completions", body,
                  {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"})
        return r["choices"][0]["message"]["content"], r.get("usage", {})


class GeminiProvider(Provider):
    name = "gemini"

    def _call(self, prompt):
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
               f"?key={os.environ['GEMINI_API_KEY']}")
        cfg = {"responseMimeType": "application/json"}
        if self.temperature is not None:
            cfg["temperature"] = self.temperature
        r = _post(url, {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": cfg}, {})
        text = "".join(p.get("text", "") for p in r["candidates"][0]["content"]["parts"])
        return text, r.get("usageMetadata", {})


class AnthropicProvider(Provider):
    name = "anthropic"

    def _call(self, prompt):
        body = {"model": self.model, "max_tokens": 8000, "messages": [{"role": "user", "content": prompt}]}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        r = _post("https://api.anthropic.com/v1/messages", body,
                  {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
        text = "".join(b.get("text", "") for b in r["content"] if b.get("type") == "text")
        return text, r.get("usage", {})


class MockProvider(Provider):
    """Offline stand-in: answers interpretation prompts from ground truth with a
    configurable error rate. Used for tests and for dry runs of the harness."""
    name = "mock"

    def __init__(self, truth: Dict[str, Dict], eps: float = 0.0, seed: int = 0):
        super().__init__("mock")
        self.truth = truth
        self.eps = eps
        self.rng = random.Random(seed)

    def _call(self, prompt):
        cats = ["school", "child_activity", "child_medical", "work", "caregiver_medical", "errand", "personal"]
        out = []
        for eid, lab in self.truth.items():
            lab = dict(lab)
            if self.rng.random() < self.eps:
                lab["category"] = self.rng.choice(cats)
            out.append({"event_id": eid, **lab, "rationale": "mock"})
        return json.dumps({"events": out}), {"prompt_tokens": len(prompt) // 4}


def make_provider(spec: str, temperature: Optional[float] = None) -> Provider:
    """spec like 'openai:gpt-5.2', 'gemini:gemini-3.1-pro-preview', 'anthropic:claude-...'."""
    kind, model = spec.split(":", 1)
    cls = {"openai": OpenAIProvider, "gemini": GeminiProvider, "anthropic": AnthropicProvider}[kind]
    return cls(model, temperature)
