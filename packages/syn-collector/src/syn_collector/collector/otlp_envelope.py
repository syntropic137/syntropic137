"""Typed read-only views over the OTLP/JSON metrics and logs export requests.

Each view is a frozen dataclass wrapping ONE object of the raw request body,
so everything in ``otlp.py`` reads attributes instead of string keys and the
OTLP wire names live only here.

The views are deliberately lazy and validate nothing. A field is read only
when the parser asks for it, with the exact lookup, default and precedence the
dict-based parser used, so the collector accepts and stores precisely what it
did before (#673): fields it never reads (unknown metrics, an unselected
``sum``, the body of a known log event) cannot fail a request, an explicit
``null`` stays ``null``, and a leaf value reaches ``CollectedEvent.data``
unconverted (OTLP/JSON sends int64 and special doubles as strings).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

type OtlpScalar = str | int | float | bool
"""A scalar attribute value, exactly as it appeared in the payload."""


@dataclass(frozen=True)
class _OtlpView:
    # The raw OTLP/JSON object this view reads; nothing outside this module
    # indexes it. Accessors return leaves as sent, unvalidated, because the
    # collector must keep accepting and storing exactly what it did (module
    # docstring); each ``type: ignore[no-any-return]`` below is that choice,
    # with the declared return type naming what OTLP/JSON specifies there.
    raw: dict[str, Any]

    def _snake_or_camel(self, snake: str, camel: str, default: Any) -> Any:  # noqa: ANN401
        """Read ``snake``, falling back to ``camel``, then ``default``."""
        return self.raw.get(snake, self.raw.get(camel, default))


class OtlpAnyValue(_OtlpView):
    """OTel ``AnyValue``: one of string, int, double or bool."""

    def scalar(self) -> OtlpScalar:
        """The first kind PRESENT, in string/int/double/bool order, else ``""``.

        Presence, not non-null: ``{"intValue": null}`` is ``None``.
        """
        for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
            if key in self.raw:
                return self.raw[key]  # type: ignore[no-any-return]
        return ""

    def string_value(self, default: str) -> str:
        """``stringValue`` as sent (including ``null``), or ``default`` when absent."""
        return self.raw.get("stringValue", default)  # type: ignore[no-any-return]


class OtlpAttribute(_OtlpView):
    """OTel ``KeyValue``."""

    @property
    def key(self) -> str:
        return self.raw.get("key", "")  # type: ignore[no-any-return]

    @property
    def value(self) -> OtlpAnyValue:
        return OtlpAnyValue(self.raw.get("value", {}))


def _attributes(view: _OtlpView) -> list[OtlpAttribute]:
    return [OtlpAttribute(attr) for attr in view.raw.get("attributes", [])]


def attributes_to_dict(attributes: list[OtlpAttribute]) -> dict[str, OtlpScalar]:
    """Flatten attributes to ``key -> scalar``, in payload order, last key wins."""
    return {attr.key: attr.value.scalar() for attr in attributes}


class OtlpResource(_OtlpView):
    @property
    def attributes(self) -> list[OtlpAttribute]:
        return _attributes(self)

    def session_id(self) -> str:
        """The first ``session.id`` attribute's ``stringValue``, stringified, or ``"unknown"``."""
        for attr in self.attributes:
            if attr.key == "session.id":
                return str(attr.value.string_value("unknown"))
        return "unknown"


class OtlpNumberDataPoint(_OtlpView):
    @property
    def time_unix_nano(self) -> int | str:
        return self._snake_or_camel("time_unix_nano", "timeUnixNano", 0)  # type: ignore[no-any-return]

    @property
    def value(self) -> int | float | str:
        raw = self.raw
        return raw.get("asDouble", raw.get("asInt", raw.get("as_double", raw.get("as_int", 0))))  # type: ignore[no-any-return]

    @property
    def attributes(self) -> list[OtlpAttribute]:
        return _attributes(self)


class OtlpMetric(_OtlpView):
    @property
    def name(self) -> str:
        return self.raw.get("name", "")  # type: ignore[no-any-return]

    def data_points(self) -> list[OtlpNumberDataPoint]:
        """Data points of the first non-empty section: gauge, then sum, then histogram."""
        for key in ("gauge", "sum", "histogram"):
            section = self.raw.get(key)
            if section:
                points = section.get("data_points", section.get("dataPoints", []))
                return [OtlpNumberDataPoint(point) for point in points]
        return []


class OtlpScopeMetrics(_OtlpView):
    @property
    def metrics(self) -> list[OtlpMetric]:
        return [OtlpMetric(metric) for metric in self.raw.get("metrics", [])]


class OtlpResourceMetrics(_OtlpView):
    @property
    def resource(self) -> OtlpResource:
        return OtlpResource(self.raw.get("resource", {}))

    @property
    def scope_metrics(self) -> list[OtlpScopeMetrics]:
        scopes = self._snake_or_camel("scope_metrics", "scopeMetrics", [])
        return [OtlpScopeMetrics(scope) for scope in scopes]


class OtlpMetricsRequest(_OtlpView):
    """``ExportMetricsServiceRequest``."""

    @property
    def resource_metrics(self) -> list[OtlpResourceMetrics]:
        resources = self._snake_or_camel("resource_metrics", "resourceMetrics", [])
        return [OtlpResourceMetrics(resource) for resource in resources]


class OtlpLogRecord(_OtlpView):
    @property
    def time_unix_nano(self) -> int | str:
        return self._snake_or_camel("time_unix_nano", "timeUnixNano", 0)  # type: ignore[no-any-return]

    @property
    def severity_text(self) -> str:
        return self._snake_or_camel("severity_text", "severityText", "INFO")  # type: ignore[no-any-return]

    @property
    def body(self) -> OtlpAnyValue:
        return OtlpAnyValue(self.raw.get("body", {}))

    @property
    def attributes(self) -> list[OtlpAttribute]:
        return _attributes(self)


class OtlpScopeLogs(_OtlpView):
    @property
    def log_records(self) -> list[OtlpLogRecord]:
        records = self._snake_or_camel("log_records", "logRecords", [])
        return [OtlpLogRecord(record) for record in records]


class OtlpResourceLogs(_OtlpView):
    @property
    def resource(self) -> OtlpResource:
        return OtlpResource(self.raw.get("resource", {}))

    @property
    def scope_logs(self) -> list[OtlpScopeLogs]:
        scopes = self._snake_or_camel("scope_logs", "scopeLogs", [])
        return [OtlpScopeLogs(scope) for scope in scopes]


class OtlpLogsRequest(_OtlpView):
    """``ExportLogsServiceRequest``."""

    @property
    def resource_logs(self) -> list[OtlpResourceLogs]:
        resources = self._snake_or_camel("resource_logs", "resourceLogs", [])
        return [OtlpResourceLogs(resource) for resource in resources]
