"""Scalar query filtering configuration module."""
from __future__ import annotations

from typing import Union

from sentry.api.event_search import ParenExpression, SearchFilter
from sentry.replays.lib.new_query.conditions import IPv4Scalar, StringArray, StringScalar, UUIDArray
from sentry.replays.lib.new_query.fields import ColumnField, StringColumnField, UUIDColumnField
from sentry.replays.lib.new_query.parsers import parse_str, parse_uuid
from sentry.replays.usecases.query.conditions import ErrorIdsArray
from sentry.replays.usecases.query.fields import ComputedField, TagField

# Static Search Config
static_search_config: dict[str, ColumnField] = {
    "browser.name": StringColumnField("browser_name", parse_str, StringScalar),
    "browser.version": StringColumnField("browser_version", parse_str, StringScalar),
    "device.brand": StringColumnField("device_brand", parse_str, StringScalar),
    "device.family": StringColumnField("device_family", parse_str, StringScalar),
    "device.model": StringColumnField("device_model", parse_str, StringScalar),
    "device.name": StringColumnField("device_name", parse_str, StringScalar),
    "dist": StringColumnField("dist", parse_str, StringScalar),
    "environment": StringColumnField("environment", parse_str, StringScalar),
    "id": StringColumnField("replay_id", lambda x: str(parse_uuid(x)), StringScalar),
    "os.name": StringColumnField("os_name", parse_str, StringScalar),
    "os.version": StringColumnField("os_version", parse_str, StringScalar),
    "platform": StringColumnField("platform", parse_str, StringScalar),
    "releases": StringColumnField("release", parse_str, StringScalar),
    "sdk.name": StringColumnField("sdk_name", parse_str, StringScalar),
    "sdk.version": StringColumnField("sdk_version", parse_str, StringScalar),
}

# Varying Search Config
#
# Fields in this configuration file can vary.  This makes it difficult to draw conclusions when
# multiple conditions are strung together.  By isolating these values into a separate config we
# are codifying a rule which should be enforced elsewhere in code: "only one condition from this
# config allowed".
varying_search_config: dict[str, Union[ColumnField, ComputedField, TagField]] = {
    "error_ids": ComputedField(parse_uuid, ErrorIdsArray),
    "trace_ids": UUIDColumnField("trace_ids", parse_uuid, UUIDArray),
    "urls": StringColumnField("urls", parse_str, StringArray),
    "user.email": StringColumnField("user_email", parse_str, StringScalar),
    "user.id": StringColumnField("user_id", parse_str, StringScalar),
    "user.ip_address": StringColumnField("ip_address_v4", parse_str, IPv4Scalar),
    "user.username": StringColumnField("user_name", parse_str, StringScalar),
}


scalar_search_config = {**static_search_config, **varying_search_config}


def can_scalar_search_subquery(
    search_filters: list[Union[ParenExpression, SearchFilter, str]]
) -> bool:
    """Return "True" if a scalar event search can be performed."""
    has_seen_varying_field = False

    for search_filter in search_filters:
        # String operators have no value here. We can skip them.
        if isinstance(search_filter, str):
            continue
        # ParenExpressions are recursive.  So we recursively call our own function and return early
        # if any of the fields fail.
        elif isinstance(search_filter, ParenExpression):
            is_ok = can_scalar_search_subquery(search_filter.children)
            if not is_ok:
                return False
        else:
            name = search_filter.key.name

            # If the search-filter does not exist in either configuration then return false.
            if name not in static_search_config and name not in varying_search_config:
                return False

            if name in varying_search_config:
                # If a varying field has been seen before then we can't use a row-based sub-query. We
                # need to use an aggregation query to ensure the two values are found or not found
                # within the context of the aggregate replay.
                if has_seen_varying_field:
                    return False

                # Negated conditionals require knowledge of the aggregate state to determine if the
                # value truly does not exist in the aggregate replay result.
                if search_filter.operator in ("!=", "NOT IN"):
                    return False

                has_seen_varying_field = True

    # The set of filters are considered valid if the function did not return early.
    return True
