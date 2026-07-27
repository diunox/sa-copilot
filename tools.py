"""SA Copilot tools — every tool is a REAL call: DO public API (read-only token),
local repo files (incl. diagram images), or a live-site screenshot.

Tool results returned to the model are JSON strings; executors never mutate anything.
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import subprocess
import tempfile

import httpx

DO_API = "https://api.digitalocean.com"

SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_regions",
            "description": "List DigitalOcean datacenter regions (slug, name, available features).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_sizes",
            "description": "List droplet sizes with vCPU/memory/disk and monthly/hourly USD pricing. Optionally filter to sizes available in a region slug.",
            "parameters": {
                "type": "object",
                "properties": {"region": {"type": "string", "description": "region slug, e.g. nyc3"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_app_spec",
            "description": "Validate a DigitalOcean App Platform app spec and get the projected monthly cost, via the propose endpoint (read-only dry run; nothing is created).",
            "parameters": {
                "type": "object",
                "properties": {"spec": {"type": "object", "description": "App Platform app spec"}},
                "required": ["spec"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_repo_files",
            "description": "List files in the customer's repository (path + size). Use to find code, manifests, and diagrams.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_repo_file",
            "description": "Read a text file from the customer's repository (truncated to 8000 chars).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "view_image",
            "description": "Load an image (repo diagram or screenshot) so you can SEE it. Returns a marker; the image is attached to your next turn.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "repo-relative image path, or 'SCREENSHOT' for the latest site screenshot"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screenshot_site",
            "description": "Take a fresh screenshot of the deployed site URL (headless browser). Follow with view_image('SCREENSHOT') to inspect it.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


class Toolbox:
    def __init__(self, api_token: str, repo_dir: str, site_url: str):
        self.repo = pathlib.Path(repo_dir).resolve()
        self.site_url = site_url
        self.http = httpx.Client(
            timeout=30, headers={"Authorization": f"Bearer {api_token}"} if api_token else {}
        )
        self.last_screenshot: bytes | None = None
        self.pending_image: tuple[str, bytes] | None = None  # (label, png bytes)

    # ---- DO API ----
    def list_regions(self) -> str:
        r = self.http.get(f"{DO_API}/v2/regions", params={"per_page": 200})
        r.raise_for_status()
        rows = [
            {"slug": x["slug"], "name": x["name"], "available": x["available"]}
            for x in r.json()["regions"]
        ]
        return json.dumps({"regions": rows})

    def list_sizes(self, region: str | None = None) -> str:
        r = self.http.get(f"{DO_API}/v2/sizes", params={"per_page": 200})
        r.raise_for_status()
        rows = []
        for s in r.json()["sizes"]:
            if region and region not in s["regions"]:
                continue
            rows.append(
                {
                    "slug": s["slug"],
                    "vcpus": s["vcpus"],
                    "memory_mb": s["memory"],
                    "disk_gb": s["disk"],
                    "usd_monthly": s["price_monthly"],
                    "usd_hourly": s["price_hourly"],
                }
            )
        rows.sort(key=lambda x: x["usd_monthly"])
        return json.dumps({"sizes": rows[:40], "note": f"{len(rows)} sizes, cheapest 40 shown"})

    def validate_app_spec(self, spec: dict) -> str:
        r = self.http.post(f"{DO_API}/v2/apps/propose", json={"spec": spec})
        if r.status_code >= 400:
            return json.dumps({"valid": False, "status": r.status_code, "error": r.text[:800]})
        return json.dumps({"valid": True, "propose": r.json()})

    # ---- repo ----
    def _safe(self, path: str) -> pathlib.Path:
        p = (self.repo / path).resolve()
        if not str(p).startswith(str(self.repo)):
            raise ValueError("path escapes repo")
        return p

    def list_repo_files(self) -> str:
        rows = []
        for p in sorted(self.repo.rglob("*")):
            if p.is_file() and ".git" not in p.parts:
                rows.append({"path": str(p.relative_to(self.repo)), "bytes": p.stat().st_size})
        return json.dumps({"files": rows[:200]})

    def read_repo_file(self, path: str) -> str:
        p = self._safe(path)
        try:
            return json.dumps({"path": path, "content": p.read_text(errors="replace")[:8000]})
        except Exception as e:
            return json.dumps({"path": path, "error": str(e)[:200]})

    # ---- vision ----
    def view_image(self, path: str) -> str:
        if path == "SCREENSHOT":
            if not self.last_screenshot:
                return json.dumps({"error": "no screenshot taken yet — call screenshot_site first"})
            self.pending_image = ("screenshot", self.last_screenshot)
            return json.dumps({"attached": "screenshot", "note": "image attached to your next turn"})
        p = self._safe(path)
        if not p.exists() or p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            return json.dumps({"error": f"not a readable image: {path}"})
        self.pending_image = (path, p.read_bytes())
        return json.dumps({"attached": path, "note": "image attached to your next turn"})

    def screenshot_site(self) -> str:
        out = pathlib.Path(tempfile.mkstemp(suffix=".png")[1])
        try:
            subprocess.run(
                ["playwright", "screenshot", "--full-page", self.site_url, str(out)],
                check=True, capture_output=True, timeout=60,
            )
            self.last_screenshot = out.read_bytes()
            return json.dumps({"ok": True, "url": self.site_url, "bytes": len(self.last_screenshot)})
        except Exception as e:
            cached = os.environ.get("COPILOT_SCREENSHOT_FALLBACK")
            if cached and pathlib.Path(cached).exists():
                self.last_screenshot = pathlib.Path(cached).read_bytes()
                return json.dumps({"ok": True, "url": self.site_url, "cached_fallback": True})
            return json.dumps({"ok": False, "error": str(e)[:300]})
        finally:
            out.unlink(missing_ok=True)

    def execute(self, name: str, args: dict) -> str:
        fn = getattr(self, name, None)
        if not fn or name.startswith("_"):
            return json.dumps({"error": f"unknown tool {name}"})
        try:
            return fn(**args)
        except Exception as e:
            return json.dumps({"error": f"{type(e).__name__}: {e}"[:400]})
