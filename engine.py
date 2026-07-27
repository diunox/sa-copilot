"""SA Copilot agentic loop — model-parameterized (the A/B lever), receipts on every step.

Yields event dicts the UI renders live:
  {"ev":"step", ...}       model turn receipt (tokens incl cached/reasoning, latency, cost)
  {"ev":"tool", ...}       tool executed (name, args, result preview, ms)
  {"ev":"text", "delta"}   assistant text
  {"ev":"done", "totals"}  end-of-run totals for the side-by-side slide
"""
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field

import httpx

from tools import SCHEMAS, Toolbox

SYSTEM = """You are the DigitalOcean SA Copilot. A customer wants their application running on
DigitalOcean. Work stepwise with your tools: inspect the repository (including any architecture
diagram — view it), choose a region and size with live pricing, validate an App Platform spec via
the propose dry-run, and finish with a concrete recommendation (region, size, projected monthly
cost). If a deployed site URL is configured, screenshot it and visually confirm it looks healthy.
Be concise; never invent prices or regions — always use the tools."""

MAX_STEPS = 12


@dataclass
class RunTotals:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    tool_calls: int = 0
    steps: int = 0
    wall_s: float = 0.0
    cost_usd: float | None = None


class Copilot:
    def __init__(self, base_url: str, api_key: str, model: str, toolbox: Toolbox,
                 price_in: float = 0.0, price_out: float = 0.0, price_cached: float = 0.0,
                 max_tokens: int = 4096):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.toolbox = toolbox
        self.price_in, self.price_out = price_in, price_out
        self.price_cached = price_cached or price_in  # no cache discount unless priced
        self.max_tokens = max_tokens
        self.http = httpx.Client(timeout=180, headers={"Authorization": f"Bearer {api_key}"})

    def _chat(self, messages: list[dict]) -> dict:
        body = {
            "model": self.model,
            "messages": messages,
            "tools": SCHEMAS,
            "tool_choice": "auto",
            "max_tokens": self.max_tokens,
            "top_p": 0.95,
        }
        r = self.http.post(f"{self.base_url}/chat/completions", json=body)
        r.raise_for_status()
        return r.json()

    def run(self, task: str):
        t0 = time.time()
        totals = RunTotals()
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": task},
        ]
        for step in range(1, MAX_STEPS + 1):
            ts = time.time()
            resp = self._chat(messages)
            dt = round(time.time() - ts, 2)

            usage = resp.get("usage", {}) or {}
            det = usage.get("completion_tokens_details") or {}
            pdet = usage.get("prompt_tokens_details") or {}
            totals.steps = step
            totals.prompt_tokens += usage.get("prompt_tokens", 0) or 0
            totals.completion_tokens += usage.get("completion_tokens", 0) or 0
            totals.reasoning_tokens += det.get("reasoning_tokens") or 0
            totals.cached_tokens += pdet.get("cached_tokens") or 0

            choice = resp["choices"][0]
            msg = choice["message"]
            yield {
                "ev": "step", "n": step, "model": self.model, "sec": dt,
                "finish": choice.get("finish_reason"),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "reasoning_tokens": det.get("reasoning_tokens"),
                "cached_tokens": pdet.get("cached_tokens"),
            }
            if msg.get("content"):
                yield {"ev": "text", "delta": msg["content"]}

            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                # K3 gotcha: a "length" finish is a truncated turn, not a conclusion —
                # feed it back and let the model finish the job.
                if choice.get("finish_reason") == "length" and step < MAX_STEPS:
                    messages.append({"role": "assistant", "content": msg.get("content") or ""})
                    messages.append({"role": "user",
                                     "content": "You were cut off. Continue — finish the remaining steps and the final recommendation."})
                    continue
                break

            messages.append(msg)
            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                tt = time.time()
                result = self.toolbox.execute(name, args)
                totals.tool_calls += 1
                yield {
                    "ev": "tool", "name": name, "args": args,
                    "ms": round((time.time() - tt) * 1000),
                    "result_preview": result[:400],
                }
                messages.append({
                    "role": "tool", "tool_call_id": tc["id"], "name": name, "content": result,
                })
                # a view_image tool attaches the actual image to the NEXT user-visible turn
                if self.toolbox.pending_image:
                    label, png = self.toolbox.pending_image
                    self.toolbox.pending_image = None
                    messages.append({
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"[attached image: {label}]"},
                            {"type": "image_url", "image_url": {
                                "url": "data:image/png;base64," + base64.b64encode(png).decode()}},
                        ],
                    })

        totals.wall_s = round(time.time() - t0, 1)
        if self.price_in and self.price_out:
            totals.cost_usd = round(
                (totals.prompt_tokens - totals.cached_tokens) * self.price_in / 1e6
                + totals.cached_tokens * self.price_cached / 1e6
                + totals.completion_tokens * self.price_out / 1e6, 6)
        yield {"ev": "done", "totals": totals.__dict__}
