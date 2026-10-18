"""Content screening (X-03): Model Armor in the cloud, a rule-based fake locally. Content is data, never instructions."""

from __future__ import annotations

import html
import re
from typing import Protocol

import httpx
from pydantic import BaseModel, Field

from shared.settings import Settings, get_settings

# Phrases that try to steer a model; flagged and neutralised (the text still reaches prompts, but only as data).
_INJECTION = re.compile(
    r"(ignore (all |any )?(previous|prior|above) (instructions|prompts)|disregard (the )?(system|previous)|"
    r"you are now|system prompt|act as (an? )?|new instructions?:|developer mode|jailbreak|"
    r"reveal (your|the) (prompt|instructions)|</?(system|assistant|me|content)>)", re.I)
_POLITICAL = re.compile(r"\b(election|vote for|political party|campaign rally|manifesto|ballot)\b", re.I)


class ScreenResult(BaseModel):
    """Outcome of screening one text."""

    ok: bool                       # false = refuse the content (political / election)
    flagged: list[str] = Field(default_factory=list)
    text: str                      # neutralised text, safe to wrap in a <content> block


class Screener(Protocol):
    """Screens uploaded or extracted text."""

    def screen(self, text: str) -> ScreenResult: ...


def neutralise(text: str) -> str:
    """Escape markup and defuse injection phrases so the text can only be read as data."""
    t = html.escape(text, quote=False)
    return _INJECTION.sub(lambda m: f"[quoted: {m.group(0)}]", t)


def wrap(text: str, tag: str = "content") -> str:
    """Delimited data block for prompts."""
    return f"<{tag}>\n{neutralise(text)}\n</{tag}>"


class FakeScreener:
    """Offline screener: regex rules for injections and political campaigns."""

    def screen(self, text: str) -> ScreenResult:
        """Flag injection-like and political text; always returns neutralised text."""
        flags = []
        if _INJECTION.search(text or ""):
            flags.append("prompt_injection")
        if _POLITICAL.search(text or ""):
            flags.append("political")
        return ScreenResult(ok="political" not in flags, flagged=flags, text=neutralise(text or ""))


def template_name(s: Settings) -> str:
    """Full template resource name (MODEL_ARMOR_TEMPLATE may be the full path or just the template id)."""
    t = s.model_armor_template
    return t if t.startswith("projects/") else f"projects/{s.gcp_project_id}/locations/{s.gcp_region}/templates/{t}"


class ModelArmorScreener(FakeScreener):
    """Model Armor `sanitizeUserPrompt` on the configured template, plus the local rules."""

    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def screen(self, text: str) -> ScreenResult:
        """Call Model Armor; fall back to local rules if it is unreachable."""
        base = super().screen(text)
        try:
            import google.auth
            from google.auth.transport.requests import Request

            creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            creds.refresh(Request())
            name = template_name(self.s)
            loc = name.split("/locations/")[1].split("/")[0]
            url = f"https://modelarmor.{loc}.rep.googleapis.com/v1/{name}:sanitizeUserPrompt"
            r = httpx.post(url, json={"userPromptData": {"text": text}}, timeout=10,
                           headers={"Authorization": f"Bearer {creds.token}"})
            res = r.json().get("sanitizationResult", {})
            if res.get("filterMatchState") == "MATCH_FOUND":
                for name, f in (res.get("filterResults") or {}).items():
                    if "MATCH_FOUND" in str(f):
                        base.flagged.append(f"model_armor:{name}")
        except Exception:  # noqa: BLE001 — screening never blocks the studio; local rules still apply
            base.flagged.append("model_armor_unavailable")
        return base


def get_screener(settings: Settings | None = None) -> Screener:
    """Model Armor when a template is configured in the cloud, else the fake."""
    s = settings or get_settings()
    if s.env == "cloud" and s.model_armor_enabled and s.model_armor_template:
        return ModelArmorScreener(s)
    return FakeScreener()
