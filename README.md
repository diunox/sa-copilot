# SA Copilot — K3 webinar demo (presenter-only)

The "deeply comprehensible use case" from the 07-29 webinar brief: *a customer wants their app
running on DigitalOcean.* The copilot reads their repo (including the architecture diagram —
**vision**), calls **real DO APIs on screen** (regions, sizes+pricing, App Platform `propose`
dry-run — all read-only), recommends region/size/monthly-cost, then **screenshots the deployed
site and visually confirms it** (vision again). Model is a parameter — the identical app runs on
the closed-source comparator for the side-by-side segment.

**This app is NOT part of the koine-web deploy.** It runs on the presenter's machine only.

## Run
```
pip install fastapi uvicorn httpx
uvicorn app:app --port 8801
```
Optional for live screenshots: `pip install playwright && playwright install chromium`
(without it, set `COPILOT_SCREENSHOT_FALLBACK=/path/to/cached.png`).

## Env
| var | meaning |
|---|---|
| `DO_INFERENCE_KEY` | webinar serverless-inference key (dedicated, revocable after show) |
| `DO_API_TOKEN` | **READ-ONLY** DO API token (regions/sizes/apps-propose) |
| `COPILOT_MODEL` | default `kimi-k3` (hard star of the show) |
| `COMPARATOR_MODEL` | e.g. `anthropic-claude-opus-5` / `openai-gpt-5.6-sol` |
| `COPILOT_REPO_DIR` | the "customer repo" shown on stage (with a diagram PNG in it) |
| `COPILOT_SITE_URL` | deployed site for the screenshot self-check |
| `PRICE_IN_<MODEL>` / `PRICE_OUT_<MODEL>` | USD per mtok, per model (e.g. `PRICE_IN_KIMI_K3`) — enables the cost lines |
| `COPILOT_SCREENSHOT_FALLBACK` | cached PNG if playwright unavailable/fails live |

Cached prompt tokens are billed at an assumed 10% of input price in the cost line — adjust in
`engine.py` when the real cache pricing is confirmed.

## Receipts (the whole point)
Every model turn emits tokens in/out, **cached** tokens (prompt caching on the growing tool-loop
prefix), **thinking** (reasoning) tokens, latency; every tool call shows args + result + ms. The
footer totals line is the side-by-side slide: steps · tool calls · wall time · tokens · $.

Verified on the platform 07-27 (`planning/webinar-k3-2026-07-28/gauntlet.py` in the homelab repo):
K3 tool-calling 6.2s · vision 10.3s · prompt cache 1536/1908 · server-side web_search works (137s).
