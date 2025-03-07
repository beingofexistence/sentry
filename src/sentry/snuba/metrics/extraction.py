import hashlib
import logging
import re
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypedDict,
    TypeVar,
    Union,
    cast,
)

from django.utils.functional import cached_property
from typing_extensions import NotRequired

from sentry.api import event_search
from sentry.api.event_search import AggregateFilter, ParenExpression, SearchFilter
from sentry.constants import DataCategory
from sentry.discover.arithmetic import is_equation
from sentry.exceptions import InvalidSearchQuery
from sentry.models import Project, ProjectTransactionThreshold, TransactionMetric
from sentry.search.events import fields
from sentry.snuba.dataset import Dataset
from sentry.snuba.metrics.utils import MetricOperationType
from sentry.utils.snuba import is_measurement, is_span_op_breakdown, resolve_column

logger = logging.getLogger(__name__)

# Name component of MRIs used for custom alert metrics.
CUSTOM_ALERT_METRIC_NAME = "transactions/on_demand"
QUERY_HASH_KEY = "query_hash"

# Base type for conditions to evaluate on payloads.
# TODO: Streamline with dynamic sampling.
RuleCondition = Union["LogicalRuleCondition", "ComparingRuleCondition", "NotRuleCondition"]

# Maps from Discover's field names to event protocol paths. See Relay's
# ``FieldValueProvider`` for supported fields. All fields need to be prefixed
# with "event.".
# List of UI supported search fields is defined in sentry/static/app/utils/fields/index.ts
_SEARCH_TO_PROTOCOL_FIELDS = {
    # Top-level fields
    "release": "release",
    "dist": "dist",
    "environment": "environment",
    "transaction": "transaction",
    "platform": "platform",
    # Top-level structures ("interfaces")
    "user.email": "user.email",
    "user.id": "user.id",
    "user.ip_address": "user.ip_address",
    "user.name": "user.name",
    "user.segment": "user.segment",
    "geo.city": "user.geo.city",
    "geo.country_code": "user.geo.country_code",
    "geo.region": "user.geo.region",
    "geo.subdivision": "user.geo.subdivision",
    "http.method": "request.method",
    # Subset of context fields
    "device.name": "contexts.device.name",
    "device.family": "contexts.device.family",
    "os.name": "contexts.os.name",
    "os.version": "contexts.os.version",
    "browser.name": "contexts.browser.name",
    "transaction.op": "contexts.trace.op",
    "transaction.status": "contexts.trace.status",
    "http.status_code": "contexts.response.status_code",
    # Computed fields
    "transaction.duration": "duration",
    "release.build": "release.build",
    "release.package": "release.package",
    "release.version": "release.version.short",
    # Tags, measurements, and breakdowns are mapped by the converter
}

# Maps from Discover's syntax to Relay rule condition operators.
_SEARCH_TO_RELAY_OPERATORS: Dict[str, "CompareOp"] = {
    "=": "eq",
    "!=": "eq",  # combined with external negation
    "<": "lt",
    "<=": "lte",
    ">": "gt",
    ">=": "gte",
    "IN": "eq",
    "NOT IN": "eq",  # combined with external negation
}

# Maps from parsed count_if condition args to Relay rule condition operators.
_COUNTIF_TO_RELAY_OPERATORS: Dict[str, "CompareOp"] = {
    "equals": "eq",
    "notEquals": "eq",
    "less": "lt",
    "greater": "gt",
    "lessOrEquals": "lte",
    "greaterOrEquals": "gte",
}

# Maps plain Discover functions to metric aggregation functions.
_SEARCH_TO_METRIC_AGGREGATES: Dict[str, MetricOperationType] = {
    "count": "sum",
    "count_if": "sum",
    "avg": "avg",
    "min": "min",
    "max": "max",
    "p50": "p50",
    "p75": "p75",
    "p95": "p95",
    "p99": "p99",
    # generic percentile is not supported by metrics layer.
}

# Maps plain Discover functions to derived metric functions which are understood by the metrics layer.
_SEARCH_TO_DERIVED_METRIC_AGGREGATES: Dict[str, MetricOperationType] = {
    "failure_rate": "on_demand_failure_rate",
    "apdex": "on_demand_apdex",
}

# Mapping to infer metric type from Discover function.
_AGGREGATE_TO_METRIC_TYPE = {
    "count": "c",
    "count_if": "c",
    "avg": "d",
    "max": "d",
    "p50": "d",
    "p75": "d",
    "p95": "d",
    "p99": "d",
    # With on demand metrics, evaluated metrics are actually stored, thus we have to choose a concrete metric type.
    "failure_rate": "c",
    "apdex": "c",
}

# Query fields that on their own do not require on-demand metric extraction but if present in an on-demand query
# will be converted to metric extraction conditions.
_STANDARD_METRIC_FIELDS = [
    "release",
    "dist",
    "environment",
    "transaction",
    "platform",
    "transaction.status",
    "transaction.op",
    "http.method",
    "http.status_code",
    "browser.name",
    "os.name",
    "geo.country_code",
    # These fields are skipped during on demand spec generation and will not be converted to metric extraction conditions
    "event.type",
    "project",
]

# Operators used in ``ComparingRuleCondition``.
CompareOp = Literal["eq", "gt", "gte", "lt", "lte", "glob"]

QueryOp = Literal["AND", "OR"]
QueryToken = Union[SearchFilter, QueryOp, ParenExpression]

Variables = Dict[str, Any]


class ComparingRuleCondition(TypedDict):
    """RuleCondition that compares a named field to a reference value."""

    op: CompareOp
    name: str
    value: Any


class LogicalRuleCondition(TypedDict):
    """RuleCondition that applies a logical operator to a sequence of conditions."""

    op: Literal["and", "or"]
    inner: List[RuleCondition]


class NotRuleCondition(TypedDict):
    """RuleCondition that negates an inner condition."""

    op: Literal["not"]
    inner: RuleCondition


class TagSpec(TypedDict):
    """
    Configuration for a tag to add to a metric.

    Tags values can be static if defined through `value` or dynamically queried
    from the payload if defined through `field`. These two options are mutually
    exclusive, behavior is undefined if both are specified.
    """

    key: str
    field: NotRequired[str]
    value: NotRequired[str]
    condition: NotRequired[RuleCondition]


class MetricSpec(TypedDict):
    """
    Specification for a metric to extract from some data.

    The metric type is given as part of the MRI (metric reference identifier)
    which must follow the form: `<type>:<namespace>/<name>@<unit>`.

    How the metric's value is obtained depends on the metric type:
     - Counter metrics are a special case, since the default product counters do
       not count any specific field but rather the occurrence of the event. As
       such, there is no value expression, and the field is set to `None`.
       Semantics of specifying remain undefined at this point.
     - Distribution metrics require a numeric value.
     - Set metrics require a string value, which is then emitted into the set as
       unique value. Insertion of numbers and other types is undefined.
    """

    category: Literal["transaction"]
    mri: str
    field: NotRequired[Optional[str]]
    condition: NotRequired[RuleCondition]
    tags: NotRequired[Sequence[TagSpec]]


@dataclass(frozen=True)
class SupportedBy:
    """Result of a check for standard and on-demand metric support."""

    standard_metrics: bool
    on_demand_metrics: bool

    @classmethod
    def neither(cls):
        return cls(standard_metrics=False, on_demand_metrics=False)

    @classmethod
    def both(cls):
        return cls(standard_metrics=True, on_demand_metrics=True)

    @classmethod
    def combine(cls, *supported_by):
        return cls(
            standard_metrics=all(s.standard_metrics for s in supported_by),
            on_demand_metrics=all(s.on_demand_metrics for s in supported_by),
        )


def should_use_on_demand_metrics(
    dataset: Optional[Union[str, Dataset]],
    aggregate: str,
    query: Optional[str],
    prefilling: bool = False,
) -> bool:
    """On-demand metrics are used if the aggregate and query are supported by on-demand metrics but not standard"""
    supported_datasets = [Dataset.PerformanceMetrics]
    # In case we are running a prefill, we want to support also transactions, since our goal is to start extracting
    # metrics that will be needed after a query is converted from using transactions to metrics.
    if prefilling:
        supported_datasets.append(Dataset.Transactions)

    if not dataset or Dataset(dataset) not in supported_datasets:
        return False

    aggregate_supported_by = _get_aggregate_supported_by(aggregate)
    query_supported_by = _get_query_supported_by(query)

    supported_by = SupportedBy.combine(aggregate_supported_by, query_supported_by)

    return not supported_by.standard_metrics and supported_by.on_demand_metrics


def _get_aggregate_supported_by(aggregate: str) -> SupportedBy:
    try:
        if is_equation(aggregate):
            # TODO(Ogi): Implement support for equations
            return SupportedBy.neither()

        function, args, _ = fields.parse_function(aggregate)

        function_support = _get_function_support(function)
        args_support = _get_args_support(function, args)

        return SupportedBy.combine(function_support, args_support)

    except InvalidSearchQuery:
        logger.error(f"Failed to parse aggregate: {aggregate}", exc_info=True)

    return SupportedBy.neither()


def _get_function_support(function: str) -> SupportedBy:
    return SupportedBy(
        standard_metrics=True,
        on_demand_metrics=(
            function in _SEARCH_TO_METRIC_AGGREGATES
            or function in _SEARCH_TO_DERIVED_METRIC_AGGREGATES
        )
        and function in _AGGREGATE_TO_METRIC_TYPE,
    )


def _get_args_support(function: str, args: Sequence[str]) -> SupportedBy:
    # apdex can have two variations, either apdex() or apdex(value).
    if function == "apdex" and len(args) < 2:
        return SupportedBy.both()

    if len(args) == 0:
        return SupportedBy.both()

    arg = args[0]

    standard_metrics = _is_standard_metrics_field(arg)
    on_demand_metrics = _is_on_demand_supported_field(arg)

    return SupportedBy(standard_metrics=standard_metrics, on_demand_metrics=on_demand_metrics)


def _get_query_supported_by(query: Optional[str]) -> SupportedBy:
    try:
        parsed_query = event_search.parse_search_query(query)

        standard_metrics = _is_standard_metrics_query(parsed_query)
        on_demand_metrics = _is_on_demand_supported_query(parsed_query)

        return SupportedBy(standard_metrics=standard_metrics, on_demand_metrics=on_demand_metrics)
    except InvalidSearchQuery:
        logger.error(f"Failed to parse search query: {query}", exc_info=True)
        return SupportedBy.neither()


def _is_standard_metrics_query(tokens: Sequence[QueryToken]) -> bool:
    """
    Recursively checks if any of the supplied token contain search filters that can't be handled by standard metrics.
    """

    for token in tokens:
        if not _is_standard_metrics_search_filter(token):
            return False

    return True


def _is_standard_metrics_search_filter(token: QueryToken) -> bool:
    if isinstance(token, SearchFilter):
        return _is_standard_metrics_search_term(token.key.name)

    if isinstance(token, ParenExpression):
        return _is_standard_metrics_query(token.children)

    return True


def _is_on_demand_supported_query(tokens: Sequence[QueryToken]) -> bool:
    """
    Recursively checks if any of the supplied token contain search filters that can't be handled by standard metrics.
    """

    for token in tokens:
        if not _is_on_demand_supported_search_filter(token):
            return False

    return True


def _is_on_demand_supported_search_filter(token: QueryToken) -> bool:
    if isinstance(token, AggregateFilter):
        return False

    if isinstance(token, SearchFilter):
        if not _SEARCH_TO_RELAY_OPERATORS.get(token.operator):
            return False

        return not _is_excluding_transactions(token) and _is_on_demand_supported_field(
            token.key.name
        )

    if isinstance(token, ParenExpression):
        return _is_on_demand_supported_query(token.children)

    return True


def _is_excluding_transactions(token: SearchFilter) -> bool:
    return (
        token.key.name == "event.type"
        and token.operator == "!="
        and token.value.raw_value == "transaction"
    )


def _is_standard_metrics_field(field: str) -> bool:
    return (
        _is_standard_metrics_search_term(field)
        or is_measurement(field)
        or is_span_op_breakdown(field)
        or field == "transaction.duration"
    )


def _is_standard_metrics_search_term(field: str) -> bool:
    return field in _STANDARD_METRIC_FIELDS


def _is_on_demand_supported_field(field: str) -> bool:
    try:
        _map_field_name(field)
        return True
    except ValueError:
        return False


def to_standard_metrics_query(query: str) -> str:
    """
    Converts a query containing on demand search fields to a query that can be
    run using only standard metrics.

    This is done by removing conditions requiring on-demand metrics.

    NOTE: This does **NOT** create an equivalent query. It only creates the best
    approximation available using only standard metrics. It is used for approximating
    the volume of an on-demand metrics query using a combination of indexed and metrics data.

    Examples:
        "environment:dev AND transaction.duration:>=1s" -> "environment:dev"
        "environment:dev OR transaction.duration:>=1s" -> "environment:dev"
        "transaction.duration:>=1s OR browser.version:1" -> ""
        "transaction.duration:>=1s AND browser.version:1" -> ""
    """
    try:
        tokens = event_search.parse_search_query(query)
    except InvalidSearchQuery:
        logger.error(f"Failed to parse search query: {query}", exc_info=True)
        raise

    cleaned_query = to_standard_metrics_tokens(tokens)
    return query_tokens_to_string(cleaned_query)


def to_standard_metrics_tokens(tokens: Sequence[QueryToken]) -> Sequence[QueryToken]:
    """
    Converts a query in token form containing on-demand search fields to a query
    that has all on-demand filters removed and can be run using only standard metrics.
    """
    remaining_tokens = _remove_on_demand_search_filters(tokens)
    cleaned_query = cleanup_query(remaining_tokens)
    return cleaned_query


def query_tokens_to_string(tokens: Sequence[QueryToken]) -> str:
    """
    Converts a list of tokens into a query string.
    """
    ret_val = ""
    for token in tokens:
        if isinstance(token, str):
            ret_val += f" {token}"
        else:
            ret_val += f" {token.to_query_string()}"
    return ret_val.strip()


def _remove_on_demand_search_filters(tokens: Sequence[QueryToken]) -> Sequence[QueryToken]:
    """
    removes tokens that contain filters that can only be handled by on demand metrics.
    """
    ret_val: List[QueryToken] = []
    for token in tokens:
        if isinstance(token, SearchFilter):
            if _is_standard_metrics_search_filter(token):
                ret_val.append(token)
        elif isinstance(token, ParenExpression):
            ret_val.append(ParenExpression(_remove_on_demand_search_filters(token.children)))
        else:
            ret_val.append(token)
    return ret_val


def cleanup_query(tokens: Sequence[QueryToken]) -> Sequence[QueryToken]:
    """
    Recreates a valid query from an original query that has had on demand search filters removed.

    When removing filters from a query it is possible to create invalid queries.
    For example removing the on demand filters from "transaction.duration:>=1s OR browser.version:1 AND environment:dev"
    would result in "OR AND environment:dev" which is not a valid query this should be cleaned to "environment:dev.

    "release:internal and browser.version:1 or os.name:android" => "release:internal or and os.name:android" which would be
    cleaned to "release:internal or os.name:android"
    """
    tokens = list(tokens)

    # remove empty parens
    removed_empty_parens: List[QueryToken] = []
    for token in tokens:
        if not isinstance(token, ParenExpression):
            removed_empty_parens.append(token)
        else:
            children = cleanup_query(token.children)
            if len(children) > 0:
                removed_empty_parens.append(ParenExpression(children))
    # remove AND and OR operators at the start of the query
    while len(removed_empty_parens) > 0 and isinstance(removed_empty_parens[0], str):
        removed_empty_parens.pop(0)

    # remove AND and OR operators at the end of the query
    while len(removed_empty_parens) > 0 and isinstance(removed_empty_parens[-1], str):
        removed_empty_parens.pop()

    # remove AND and OR operators that are next to each other
    ret_val = []
    previous_token: Optional[QueryToken] = None

    for token in removed_empty_parens:
        # this loop takes care of removing consecutive AND/OR operators (keeping only one of them)
        if isinstance(token, str) and isinstance(previous_token, str):
            token = cast(QueryOp, token.upper())
            # this handles two AND/OR operators next to each other, we must drop one of them
            # if we have an AND do nothing (AND will be merged in the previous token see comment below)
            # if we have an OR the resulting operator will be an OR
            # AND OR => OR
            # OR OR => OR
            # OR AND => OR
            # AND AND => AND
            if token == "OR":
                previous_token = "OR"
            continue
        elif previous_token is not None:
            ret_val.append(previous_token)
        previous_token = token
    # take care of the last token (if any)
    if previous_token is not None:
        ret_val.append(previous_token)

    return ret_val


def _deep_sorted(value: Union[Any, Dict[Any, Any]]) -> Union[Any, Dict[Any, Any]]:
    if isinstance(value, dict):
        return {key: _deep_sorted(value) for key, value in sorted(value.items())}
    else:
        return value


TagsSpecsGenerator = Callable[[Project, Optional[str]], List[TagSpec]]


def failure_rate_tag_spec(_1: Project, _2: Optional[str]) -> List[TagSpec]:
    return [
        {
            "key": "failure",
            "value": "true",
            "condition": {
                "inner": {
                    "name": "event.contexts.trace.status",
                    "op": "eq",
                    "value": ["ok", "cancelled", "unknown"],
                },
                "op": "not",
            },
        }
    ]


def apdex_tag_spec(project: Project, argument: Optional[str]) -> List[TagSpec]:
    _, metric = _get_apdex_project_transaction_threshold(project)

    # TODO: we can also opt to fallback on the db threshold in case it's not supplied, but we have to see if we want to
    #  support that.
    if argument is None:
        raise Exception("apdex requires a threshold parameter.")

    field = _map_field_name(metric)
    apdex_threshold = int(argument)

    return [
        {
            "key": "satisfaction",
            "value": "satisfactory",
            "condition": {"name": field, "op": "lte", "value": apdex_threshold},
        },
        {
            "key": "satisfaction",
            "value": "tolerable",
            "condition": {
                "inner": [
                    {"name": field, "op": "gt", "value": apdex_threshold},
                    {"name": field, "op": "lte", "value": apdex_threshold * 4},
                ],
                "op": "and",
            },
        },
        {
            "key": "satisfaction",
            "value": "frustrated",
            "condition": {"name": field, "op": "gt", "value": apdex_threshold * 4},
        },
    ]


_DERIVED_METRICS: Dict[MetricOperationType, TagsSpecsGenerator] = {
    "on_demand_failure_rate": failure_rate_tag_spec,
    "on_demand_apdex": apdex_tag_spec,
}


def is_derived_metric(op: MetricOperationType) -> bool:
    return op in _DERIVED_METRICS


@dataclass(frozen=True)
class FieldParsingResult:
    function: str
    arguments: List[str]
    alias: str


@dataclass(frozen=True)
class QueryParsingResult:
    conditions: Sequence[QueryToken]


@dataclass
class OnDemandMetricSpec:
    """
    Contains the information required to query or extract an on-demand metric.
    """

    # Base fields from outside.
    field: str
    query: str

    # Public fields.
    op: MetricOperationType

    # Private fields.
    _metric_type: str
    _argument: Optional[str]

    def __init__(self, field: str, query: str):
        self.field = field
        self.query = self._cleanup_query(query)
        self._eager_process()

    def _eager_process(self):
        op, metric_type, argument = self._process_field()

        self.op = op
        self._metric_type = metric_type
        self._argument = argument

    @property
    def field_to_extract(self):
        if self.op == "on_demand_apdex":
            return None

        return self._argument

    @cached_property
    def mri(self) -> str:
        """The unique identifier of the on-demand metric."""
        return f"{self._metric_type}:{CUSTOM_ALERT_METRIC_NAME}@none"

    @cached_property
    def query_hash(self) -> str:
        """Returns a hash of the query and field to be used as a unique identifier for the on-demand metric."""
        str_to_hash = f"{self._field_for_hash()};{self._query_for_hash()}"
        return hashlib.shake_128(bytes(str_to_hash, encoding="ascii")).hexdigest(4)

    def _field_for_hash(self) -> Optional[str]:
        # Since derived metrics are a special case, we want to make sure that the hashing is different from the other
        # metrics.
        #
        # More specifically the hashing implementation will depend on the derived metric type:
        # - failure rate -> hash the op
        # - apdex -> hash the op + value
        #
        # The rationale for different hashing is complex to explain but the main idea is that if we hash the argument
        # and the conditions, we might have a case in which `count()` with condition `f` has the same hash as `apdex()`
        # with condition `f` and this will create a problem, since we might already have data for the `count()` and when
        # `apdex()` is created in the UI, we will use that metric but that metric didn't extract in the past the tags
        # that are used for apdex calculation, effectively causing problems with the data.
        if self.op == "on_demand_failure_rate":
            return self.op
        elif self.op == "on_demand_apdex":
            return f"{self.op}:{self._argument}"

        return self._argument

    def _query_for_hash(self):
        # In order to reduce the amount of metric being extracted, we perform a sort of the conditions tree. This
        # heuristic allows us to perform some de-duplication to minimize the number of metrics extracted for
        # semantically identical queries.
        return str(_deep_sorted(self.condition))

    @cached_property
    def condition(self) -> RuleCondition:
        """Returns a parent condition containing a list of other conditions which determine whether of not the metric
        is extracted."""
        return self._process_query()

    def tags_conditions(self, project: Project) -> List[TagSpec]:
        """Returns a list of tag conditions that will specify how tags are injected into metrics by Relay."""
        tags_specs_generator = _DERIVED_METRICS.get(self.op)
        if tags_specs_generator is None:
            return []

        return tags_specs_generator(project, self._argument)

    def to_metric_spec(self, project: Project) -> MetricSpec:
        """Converts the OndemandMetricSpec into a MetricSpec that Relay can understand."""
        # Tag conditions are always computed based on the project.
        extended_tags_conditions = self.tags_conditions(project).copy()
        extended_tags_conditions.append({"key": QUERY_HASH_KEY, "value": self.query_hash})

        return {
            "category": DataCategory.TRANSACTION.api_name(),
            "mri": self.mri,
            "field": self.field_to_extract,
            "condition": self.condition,
            "tags": extended_tags_conditions,
        }

    def _process_field(self) -> Tuple[MetricOperationType, str, Optional[str]]:
        parsed_field = self._parse_field(self.field)
        if parsed_field is None:
            raise Exception(f"Unable to parse the field {self.field}")

        op = self._get_op(parsed_field.function)
        metric_type = self._get_metric_type(parsed_field.function)

        return op, metric_type, self._parse_argument(op, metric_type, parsed_field)

    def _process_query(self) -> RuleCondition:
        parsed_field = self._parse_field(self.field)
        if parsed_field is None:
            raise Exception(f"Unable to parse the field {self.field}")

        # We have to handle the special case for the "count_if" function, however it may be better to build some
        # better abstracted code to handle third-party rule conditions injection.
        count_if_rule_condition = None
        if parsed_field.function == "count_if":
            key, op, value = parsed_field.arguments
            count_if_rule_condition = _convert_countif_filter(key, op, value)

        # First step is to parse the query string into our internal AST format.
        parsed_query = self._parse_query(self.query)
        # An on demand metric must have at least a condition, otherwise we can just use a classic metric.
        if parsed_query is None or len(parsed_query.conditions) == 0:
            if count_if_rule_condition is None:
                raise Exception("This query should not use on demand metrics")

            return count_if_rule_condition

        # Second step is to generate the actual Relay rule that contains all rules nested.
        rule_condition = SearchQueryConverter(parsed_query.conditions, {}).convert()
        if not count_if_rule_condition:
            return rule_condition

        # In case we have a top level rule which is not an "and" we have to wrap it.
        if rule_condition["op"] != "and":
            return {"op": "and", "inner": [rule_condition, count_if_rule_condition]}

        # In the other case, we can just flatten the conditions.
        rule_condition["inner"].append(count_if_rule_condition)
        return rule_condition

    @staticmethod
    def _parse_argument(
        op: MetricOperationType, metric_type: str, parsed_field: FieldParsingResult
    ) -> Optional[str]:
        requires_single_argument = metric_type in ["s", "d"] or op in ["on_demand_apdex"]
        if not requires_single_argument:
            return None

        if len(parsed_field.arguments) != 1:
            raise Exception(f"The operation {op} supports only a single parameter")

        argument = parsed_field.arguments[0]
        map_argument = op not in ["on_demand_apdex"]

        return _map_field_name(argument) if map_argument else argument

    @staticmethod
    def _get_op(function: str) -> MetricOperationType:
        op = _SEARCH_TO_METRIC_AGGREGATES.get(function) or _SEARCH_TO_DERIVED_METRIC_AGGREGATES.get(
            function
        )
        if op is not None:
            return op

        raise Exception(f"Unsupported aggregate function {function}")

    @staticmethod
    def _get_metric_type(function: str) -> str:
        metric_type = _AGGREGATE_TO_METRIC_TYPE.get(function)
        if metric_type is not None:
            return metric_type

        raise Exception(f"Unsupported aggregate function {function}")

    @staticmethod
    def _cleanup_query(query: str) -> str:
        regexes = [r"event\.type:transaction\s*", r"project:[\w\d\"\-_]+\s*"]

        new_query = query
        for regex in regexes:
            new_query = re.sub(regex, "", new_query)

        return new_query

    @staticmethod
    def _parse_field(value: str) -> Optional[FieldParsingResult]:
        try:
            function, arguments, alias = fields.parse_function(value)
            return FieldParsingResult(function=function, arguments=arguments, alias=alias)
        except InvalidSearchQuery:
            return None

    @staticmethod
    def _parse_query(value: str) -> Optional[QueryParsingResult]:
        try:
            conditions = event_search.parse_search_query(value)
            return QueryParsingResult(conditions=conditions)
        except InvalidSearchQuery:
            return None


def _convert_countif_filter(key: str, op: str, value: str) -> RuleCondition:
    """Maps ``count_if`` arguments to a ``RuleCondition``."""
    assert op in _COUNTIF_TO_RELAY_OPERATORS, f"Unsupported `count_if` operator {op}"

    condition: RuleCondition = {
        "op": _COUNTIF_TO_RELAY_OPERATORS[op],
        "name": _map_field_name(key),
        "value": fields.normalize_count_if_value({"column": key, "value": value}),
    }

    if op == "notEquals":
        condition = {"op": "not", "inner": condition}

    return condition


def _map_field_name(search_key: str) -> str:
    """
    Maps the name of a field in a search query to the event protocol path.

    Raises an exception if the field is not supported.
    """
    # Map known fields using a static mapping.
    if field := _SEARCH_TO_PROTOCOL_FIELDS.get(search_key):
        return f"event.{field}"

    # Measurements support generic access.
    if search_key.startswith("measurements."):
        return f"event.{search_key}"

    # Run a schema-aware check for tags. Always use the resolver output,
    # since it accounts for passing `tags[foo]` as key.
    resolved = (resolve_column(Dataset.Transactions))(search_key)
    if resolved.startswith("tags["):
        return f"event.tags.{resolved[5:-1]}"

    raise ValueError(f"Unsupported query field {search_key}")


def _get_apdex_project_transaction_threshold(project: Project) -> Tuple[int, str]:
    result = ProjectTransactionThreshold.filter(
        organization_id=project.organization.id,
        project_ids=[project.id],
        order_by=[],
        value_list=["threshold", "metric"],
    )

    if len(result) == 0:
        # We use the default threshold shown in the UI.
        threshold = 300
        metric = TransactionMetric.DURATION.value
    else:
        # We technically don't use this threshold since we extract it from the apdex(x) field where x is the threshold,
        # but we still return it to have it in case a fallback will be needed.
        threshold, metric = result[0]

    if metric == TransactionMetric.DURATION.value:
        metric_field = "transaction.duration"
    elif metric == TransactionMetric.LCP.value:
        # We assume it's lcp since the enumerator contains only two possibilities.
        metric_field = "measurements.lcp"
    else:
        raise Exception("Invalid metric for project transaction threshold")

    return threshold, metric_field


T = TypeVar("T")


class SearchQueryConverter:
    """
    A converter from search query token stream to rule conditions.

    Pass a token stream obtained from `parse_search_query` to the constructor.
    The converter can be used exactly once.
    """

    def __init__(self, tokens: Sequence[QueryToken], variables: Variables):
        self._tokens = tokens
        # TODO: decide whether we want to inject variables in `convert` or keep them instance based.
        self._variables = variables
        self._position = 0

    def convert(self) -> RuleCondition:
        """
        Converts the token stream into a rule condition.

        This function can raise an exception if the token stream is structurally
        invalid or contains fields that are not supported by the rule engine.
        """
        condition = self._expr()

        if self._position < len(self._tokens):
            raise ValueError("Unexpected trailing tokens")

        return condition

    def _peek(self) -> Optional[QueryToken]:
        """Returns the next token without consuming it."""

        if self._position < len(self._tokens):
            return self._tokens[self._position]
        else:
            return None

    def _consume(self, pattern: Union[str, Type[T]]) -> Optional[T]:
        """
        Consumes the next token if it matches the given pattern.

        The pattern can be:
         - a literal string, in which case the token must be equal to the string
         - a type, in which case the token must be an instance of the type

        Returns the token if it matches, or ``None`` otherwise.
        """
        token = self._peek()

        if isinstance(pattern, str) and token != pattern:
            return None
        elif isinstance(pattern, type) and not isinstance(token, pattern):
            return None

        self._position += 1
        return cast(T, token)

    def _expr(self) -> RuleCondition:
        terms = [self._term()]

        while self._consume("OR") is not None:
            terms.append(self._term())

        if len(terms) == 1:
            return terms[0]
        else:
            return {"op": "or", "inner": terms}

    def _term(self) -> RuleCondition:
        factors = [self._factor()]

        while self._peek() not in ("OR", None):
            self._consume("AND")  # AND is optional and implicit, ignore if present.
            factors.append(self._factor())

        if len(factors) == 1:
            return factors[0]
        else:
            return {"op": "and", "inner": factors}

    def _factor(self) -> RuleCondition:
        if filt := self._consume(SearchFilter):
            return self._filter(filt)
        elif paren := self._consume(ParenExpression):
            return SearchQueryConverter(paren.children, self._variables).convert()
        elif token := self._peek():
            raise ValueError(f"Unexpected token {token}")
        else:
            raise ValueError("Unexpected end of query")

    def _filter(self, token: SearchFilter) -> RuleCondition:
        operator = _SEARCH_TO_RELAY_OPERATORS.get(token.operator)
        if not operator:
            raise ValueError(f"Unsupported operator {token.operator}")

        # We propagate the filter in order to give as output a better error message with more context.
        key: str = token.key.name
        value: Any = token.value.raw_value
        if operator == "eq" and token.value.is_wildcard():
            condition: RuleCondition = {
                "op": "glob",
                "name": _map_field_name(key),
                "value": [value],
            }
        else:
            # Special case: `x != ""` is the result of a `has:x` query, which
            # needs to be translated as `not(x == null)`.
            if token.operator == "!=" and value == "":
                value = None

            if isinstance(value, str):
                value = event_search.translate_escape_sequences(value)

            condition = {
                "op": operator,
                "name": _map_field_name(key),
                "value": value,
            }

        # In case we have negation operators, we have to wrap them in the `not` condition.
        if token.operator in ("!=", "NOT IN"):
            condition = {"op": "not", "inner": condition}

        return condition
