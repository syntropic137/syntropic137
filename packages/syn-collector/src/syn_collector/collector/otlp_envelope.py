"""Typed OTLP/JSON envelope for the metrics and logs export requests.

The raw request body is parsed into these models once, at the edge
(``parse_otlp_metrics`` / ``parse_otlp_logs`` in ``otlp.py``); everything
after that reads attributes instead of string keys.

These model an EXTERNAL payload, so they ignore unknown fields rather than
forbidding them: real exporters send ``unit``, ``description``,
``startTimeUnixNano``, ``traceId`` and more that the parser never reads, and
rejecting those would stop ingestion.

Every field accepts both the snake_case and the camelCase spelling, snake_case
first, which is the precedence the dict-based parser had. Leaf values use
strict types so nothing is coerced: OTLP/JSON encodes int64 as a string, and
``"5"`` must reach ``CollectedEvent.data`` as ``"5"``, not ``5``.
"""

from __future__ import annotations

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
)

type OtlpScalar = str | int | float | bool
"""A scalar attribute value, exactly as it appeared in the payload."""


class _OtlpModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class OtlpAnyValue(_OtlpModel):
    """OTel ``AnyValue``: one of string, int, double or bool."""

    string_value: StrictStr | None = Field(default=None, validation_alias="stringValue")
    int_value: StrictStr | StrictInt | None = Field(default=None, validation_alias="intValue")
    double_value: StrictInt | StrictFloat | None = Field(
        default=None, validation_alias="doubleValue"
    )
    bool_value: StrictBool | None = Field(default=None, validation_alias="boolValue")

    def scalar(self) -> OtlpScalar:
        """The first value set, in string/int/double/bool order, else ``""``."""
        for value in (self.string_value, self.int_value, self.double_value, self.bool_value):
            if value is not None:
                return value
        return ""


class OtlpAttribute(_OtlpModel):
    """OTel ``KeyValue``."""

    key: StrictStr = ""
    value: OtlpAnyValue = OtlpAnyValue()


def attributes_to_dict(attributes: list[OtlpAttribute]) -> dict[str, OtlpScalar]:
    """Flatten attributes to ``key -> scalar``, in payload order, last key wins."""
    return {attr.key: attr.value.scalar() for attr in attributes}


class OtlpResource(_OtlpModel):
    attributes: list[OtlpAttribute] = []

    def session_id(self) -> str:
        """The ``session.id`` attribute's string value, or ``"unknown"``."""
        for attr in self.attributes:
            if attr.key == "session.id":
                return attr.value.string_value if attr.value.string_value is not None else "unknown"
        return "unknown"


class OtlpNumberDataPoint(_OtlpModel):
    time_unix_nano: StrictInt | StrictStr = Field(
        default=0, validation_alias=AliasChoices("time_unix_nano", "timeUnixNano")
    )
    value: StrictInt | StrictFloat | StrictStr = Field(
        default=0, validation_alias=AliasChoices("asDouble", "asInt", "as_double", "as_int")
    )
    attributes: list[OtlpAttribute] = []


class OtlpMetricSection(_OtlpModel):
    """The body of a ``gauge``, ``sum`` or ``histogram`` metric."""

    data_points: list[OtlpNumberDataPoint] = Field(
        default=[], validation_alias=AliasChoices("data_points", "dataPoints")
    )


class OtlpMetric(_OtlpModel):
    name: StrictStr = ""
    gauge: OtlpMetricSection | None = None
    sum: OtlpMetricSection | None = None
    histogram: OtlpMetricSection | None = None

    @field_validator("gauge", "sum", "histogram", mode="before")
    @classmethod
    def _empty_section_is_absent(cls, value: object) -> object:
        # An empty section (``"gauge": {}``) falls through to the next type.
        return value or None

    def data_points(self) -> list[OtlpNumberDataPoint]:
        """Data points of the first present section: gauge, then sum, then histogram."""
        for section in (self.gauge, self.sum, self.histogram):
            if section is not None:
                return section.data_points
        return []


class OtlpScopeMetrics(_OtlpModel):
    metrics: list[OtlpMetric] = []


class OtlpResourceMetrics(_OtlpModel):
    resource: OtlpResource = OtlpResource()
    scope_metrics: list[OtlpScopeMetrics] = Field(
        default=[], validation_alias=AliasChoices("scope_metrics", "scopeMetrics")
    )


class OtlpMetricsRequest(_OtlpModel):
    """``ExportMetricsServiceRequest``."""

    resource_metrics: list[OtlpResourceMetrics] = Field(
        default=[], validation_alias=AliasChoices("resource_metrics", "resourceMetrics")
    )


class OtlpLogRecord(_OtlpModel):
    time_unix_nano: StrictInt | StrictStr = Field(
        default=0, validation_alias=AliasChoices("time_unix_nano", "timeUnixNano")
    )
    severity_text: StrictStr = Field(
        default="INFO", validation_alias=AliasChoices("severity_text", "severityText")
    )
    body: OtlpAnyValue = OtlpAnyValue()
    attributes: list[OtlpAttribute] = []


class OtlpScopeLogs(_OtlpModel):
    log_records: list[OtlpLogRecord] = Field(
        default=[], validation_alias=AliasChoices("log_records", "logRecords")
    )


class OtlpResourceLogs(_OtlpModel):
    resource: OtlpResource = OtlpResource()
    scope_logs: list[OtlpScopeLogs] = Field(
        default=[], validation_alias=AliasChoices("scope_logs", "scopeLogs")
    )


class OtlpLogsRequest(_OtlpModel):
    """``ExportLogsServiceRequest``."""

    resource_logs: list[OtlpResourceLogs] = Field(
        default=[], validation_alias=AliasChoices("resource_logs", "resourceLogs")
    )
