---
name: nonrecordingspan-patch
description: Patching OpenTelemetry NonRecordingSpan to add missing .attributes property required by Azure AI Projects SDK.
---

# NonRecordingSpan Patch

## Context
When OpenTelemetry tracing is configured but a `NonRecordingSpan` is active (e.g. when no
exporter is attached or tracing is partially initialised), the Azure AI Projects SDK
(`azure-ai-projects`) crashes with `AttributeError: 'NonRecordingSpan' object has no attribute 'attributes'`.

This knowledge applies whenever you integrate `AIProjectInstrumentor` or stream responses
from an Azure AI Foundry agent while OpenTelemetry is in the dependency tree.

## Key Facts
- `NonRecordingSpan` (from `opentelemetry-api`) is a valid span that intentionally does
  **not** record data, but the class lacks an `.attributes` property.
- The Azure AI Projects SDK accesses `span.span_instance.attributes.get(...)` internally,
  assuming every span exposes `.attributes`.
- **Root cause in the SDK**: the SDK checks `is_recording` **without parentheses**
  (`if span.is_recording:` instead of `if span.is_recording():`). Because `is_recording`
  is a bound method, it is always truthy, so the attribute-access code path executes even
  for `NonRecordingSpan`.
- The fix is a one-liner monkey-patch applied at application startup, **before** any agent
  call is made.

## Code Examples
```python
# backend/app/telemetry.py — applied during configure_telemetry()
from opentelemetry.trace import NonRecordingSpan as _NRS

if not hasattr(_NRS, "attributes"):
    _NRS.attributes = property(lambda self: {})  # type: ignore[attr-defined]
```

### When to apply
Call the patch **after** `configure_azure_monitor()` and `AIProjectInstrumentor().instrument()`
but **before** any agent invocation.

## Common Pitfalls
- Forgetting to guard with `hasattr` — future `opentelemetry-api` releases may add
  `.attributes` natively, and overwriting it would hide real data.
- Applying the patch too late (e.g. inside a request handler) — by then the SDK may
  already have thrown `AttributeError` during import-time instrumentation.
- Assuming the SDK bug is fixed — as of `azure-ai-projects ≥ 1.0.0b11` the
  parentheses-less `is_recording` check is still present.

## References
- File: `backend/app/telemetry.py` (NonRecordingSpan patch block near the end of `configure_telemetry()`)
- Upstream SDK issue: `is_recording` evaluated as truthy method reference instead of
  calling `is_recording()`.
