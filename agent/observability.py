"""Tracing and PII masking (R8, R9, E3, E4).

One trace id flows from the UI request -> API -> worker -> graph -> MCP servers ->
audit log. We use OpenTelemetry; spans are exported to Arize Phoenix when
PHOENIX_COLLECTOR_ENDPOINT is set (docker compose does this) and always to a
local JSONL file so traces can be inspected without Phoenix.
"""
from __future__ import annotations

import contextvars
import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter, SpanExportResult

from agent.settings import data_dir

_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("gigbid_trace_id", default=None)

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(?<!\w)(\+?\d[\d\s().-]{8,}\d)(?!\w)")
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")
SECRET = re.compile(r"(?i)(bearer\s+|api[_-]?key[\"'=:\s]+|token[\"'=:\s]+)([\w.\-]{8,})")


def mask_pii(value: Any) -> Any:
    """Mask emails, phones, card/IBAN numbers and bearer tokens in strings (recursively)."""
    if isinstance(value, str):
        v = SECRET.sub(lambda m: m.group(1) + "[SECRET]", value)
        v = EMAIL.sub("[EMAIL]", v)
        v = CARD.sub("[CARD]", v)
        v = IBAN.sub("[IBAN]", v)
        v = PHONE.sub("[PHONE]", v)
        return v
    if isinstance(value, dict):
        return {k: ("[SECRET]" if k.lower() in {"authorization", "access_token", "refresh_token", "password",
                                                  "api_key"} else mask_pii(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_pii(v) for v in value]
    return value


def new_trace_id() -> str:
    return uuid.uuid4().hex


def set_trace_id(tid: str | None) -> contextvars.Token:
    return _trace_id.set(tid)


def get_trace_id() -> str:
    tid = _trace_id.get()
    if not tid:
        tid = new_trace_id()
        _trace_id.set(tid)
    return tid


def trace_headers() -> dict[str, str]:
    return {"x-trace-id": get_trace_id()}


class JsonlExporter(SpanExporter):
    """Writes masked spans to data/processed/traces/<trace_id>.jsonl, grouped by GigBid trace id."""

    def __init__(self) -> None:
        self.dir = data_dir() / "traces"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def export(self, spans: list[ReadableSpan]) -> SpanExportResult:
        with self.lock:
            for s in spans:
                attrs = dict(s.attributes or {})
                tid = str(attrs.get("gigbid.trace_id", "untraced"))
                rec = {"name": s.name, "trace_id": tid, "start": s.start_time / 1e9,
                       "duration_ms": round((s.end_time - s.start_time) / 1e6, 2),
                       "status": s.status.status_code.name, "attributes": mask_pii(attrs)}
                with open(self.dir / f"{tid}.jsonl", "a") as f:
                    f.write(json.dumps(rec, default=str) + "\n")
        return SpanExportResult.SUCCESS


_provider: TracerProvider | None = None


def tracer() -> trace.Tracer:
    global _provider
    if _provider is None:
        _provider = TracerProvider(resource=Resource.create({"service.name": os.getenv("SERVICE_NAME", "gigbid")}))
        _provider.add_span_processor(SimpleSpanProcessor(JsonlExporter()))
        endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT")
        if endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")))
        trace.set_tracer_provider(_provider)
    return trace.get_tracer("gigbid")


@contextmanager
def span(name: str, **attrs: Any) -> Iterator[trace.Span]:
    t0 = time.perf_counter()
    with tracer().start_as_current_span(name) as s:
        s.set_attribute("gigbid.trace_id", get_trace_id())
        for k, v in attrs.items():
            if v is not None:
                s.set_attribute(k, v if isinstance(v, (int, float, bool)) else str(mask_pii(v))[:2000])
        try:
            yield s
        finally:
            s.set_attribute("latency_ms", round((time.perf_counter() - t0) * 1000, 2))


def read_trace(trace_id: str) -> list[dict]:
    p = data_dir() / "traces" / f"{trace_id}.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
