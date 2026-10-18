"""Faithfulness (I-09): numbers must trace to a tool result by source_ref; quotes must be verbatim and labelled."""

from __future__ import annotations

from typing import Any

from insights.tools import Ledger


def _norm(s: str) -> str:
    return " ".join(s.replace("“", '"').replace("”", '"').replace("’", "'").split()).strip(' "')


def check(answer: dict[str, Any], ledger: Ledger) -> list[str]:
    """Problems found (empty = faithful)."""
    errs: list[str] = []
    for n in answer.get("numbers", []):
        ref = n.get("source_ref") or ""
        if ref not in ledger.results:
            errs.append(f"number '{n.get('label')}' has unknown source_ref {ref!r}")
        elif not ledger.has_number(ref, float(n.get("value", 0))):
            errs.append(f"number '{n.get('label')}'={n.get('value')} not found in {ref}")
    for q in answer.get("quotes", []):
        txt = _norm(str(q.get("text", "")))
        src = next((r for r in ledger.texts.values() if txt and txt in _norm(str(r["text"]))), None)
        if src is None:
            errs.append(f"quote not verbatim: {txt[:60]!r}")
        elif bool(src["private"]) != bool(q.get("private")):
            errs.append(f"quote private label wrong: {txt[:40]!r}")
    return errs


def drop_unfaithful(answer: dict[str, Any], ledger: Ledger) -> tuple[dict[str, Any], int]:
    """Remove failing numbers/quotes; returns (answer, dropped count)."""
    keep_n, keep_q = [], []
    for n in answer.get("numbers", []):
        ref = n.get("source_ref") or ""
        if ref in ledger.results and ledger.has_number(ref, float(n.get("value", 0))):
            keep_n.append(n)
    for q in answer.get("quotes", []):
        txt = _norm(str(q.get("text", "")))
        src = next((r for r in ledger.texts.values() if txt and txt in _norm(str(r["text"]))), None)
        if src is not None:
            keep_q.append({**q, "private": bool(src["private"]), "agent_id": src.get("agent_id"),
                           "kind": src.get("kind"), "t": src.get("t")})
    dropped = len(answer.get("numbers", [])) - len(keep_n) + len(answer.get("quotes", [])) - len(keep_q)
    out = {**answer, "numbers": keep_n, "quotes": keep_q}
    if dropped:
        out["caveats"] = [*answer.get("caveats", []), f"{dropped} claim(s) were dropped because they could not be "
                                                       "traced to the data."]
    return out, dropped
