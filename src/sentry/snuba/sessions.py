import math
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence, Set, Tuple

from snuba_sdk import Request
from snuba_sdk.column import Column
from snuba_sdk.conditions import Condition, Op
from snuba_sdk.entity import Entity
from snuba_sdk.function import Function
from snuba_sdk.query import Query

from sentry import release_health
from sentry.snuba.dataset import Dataset
from sentry.utils import snuba
from sentry.utils.dates import to_datetime, to_timestamp
from sentry.utils.snuba import QueryOutsideRetentionError, parse_snuba_datetime, raw_query

DATASET_BUCKET = 3600


def _convert_duration(val):
    if math.isnan(val):
        return None
    return val / 1000.0


def _get_conditions_and_filter_keys(project_releases, environments):
    conditions = [["release", "IN", list(x[1] for x in project_releases)]]
    if environments is not None:
        conditions.append(["environment", "IN", environments])
    filter_keys = {"project_id": list({x[0] for x in project_releases})}
    return conditions, filter_keys


def _get_changed_project_release_model_adoptions(project_ids, now=None):
    """Returns the last 72 hours worth of releases."""
    if now is None:
        now = datetime.now(timezone.utc)

    start = now - timedelta(days=3)
    rv = []

    # Find all releases with adoption in the last 48 hours
    for x in raw_query(
        dataset=Dataset.Sessions,
        selected_columns=["project_id", "release"],
        groupby=["release", "project_id"],
        start=start,
        referrer="sessions.get-adoption",
        filter_keys={"project_id": list(project_ids)},
        orderby=["-project_id", "-release"],
    )["data"]:
        rv.append((x["project_id"], x["release"]))

    return rv


def _get_oldest_health_data_for_releases(project_releases, now=None):
    """Returns the oldest health data we have observed in a release
    in 90 days.  This is used for backfilling.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    conditions = [["release", "IN", [x[1] for x in project_releases]]]
    filter_keys = {"project_id": [x[0] for x in project_releases]}
    rows = raw_query(
        dataset=Dataset.Sessions,
        selected_columns=[["min", ["started"], "oldest"], "project_id", "release"],
        groupby=["release", "project_id"],
        start=now - timedelta(days=90),
        conditions=conditions,
        referrer="sessions.oldest-data-backfill",
        filter_keys=filter_keys,
    )["data"]
    rv = {}
    for row in rows:
        rv[row["project_id"], row["release"]] = row["oldest"]
    return rv


def _check_has_health_data(projects_list, now=None):
    """
    Function that returns a set of all project_ids or (project, release) if they have health data
    within the last 90 days based on a list of projects or a list of project, release combinations
    provided as an arg.
    Inputs:
        * projects_list: Contains either a list of project ids or a list of tuple (project_id,
        release)
    """

    if now is None:
        now = datetime.now(timezone.utc)

    if len(projects_list) == 0:
        return set()

    conditions = None
    projects_list = list(projects_list)
    # Check if projects_list also contains releases as a tuple of (project_id, releases)
    includes_releases = type(projects_list[0]) == tuple

    if includes_releases:
        filter_keys = {"project_id": {x[0] for x in projects_list}}
        conditions = [["release", "IN", [x[1] for x in projects_list]]]
        query_cols = ["release", "project_id"]

        def data_tuple(x):
            return x["project_id"], x["release"]

    else:
        filter_keys = {"project_id": {x for x in projects_list}}
        query_cols = ["project_id"]

        def data_tuple(x):
            return x["project_id"]

    raw_query_args = {
        "dataset": Dataset.Sessions,
        "selected_columns": query_cols,
        "groupby": query_cols,
        "start": now - timedelta(days=90),
        "referrer": "sessions.health-data-check",
        "filter_keys": filter_keys,
    }
    if conditions is not None:
        raw_query_args.update({"conditions": conditions})

    return {data_tuple(x) for x in raw_query(**raw_query_args)["data"]}


def _check_releases_have_health_data(
    organization_id: int,
    project_ids: List[int],
    release_versions: List[str],
    start: datetime,
    end: datetime,
) -> Set[str]:
    """
    Returns a set of all release versions that have health data within a given period of time.
    """
    if not release_versions:
        return set()

    query = Query(
        match=Entity("sessions"),
        select=[Column("release")],
        groupby=[Column("release")],
        where=[
            Condition(Column("started"), Op.GTE, start),
            Condition(Column("started"), Op.LT, end),
            Condition(Column("org_id"), Op.EQ, organization_id),
            Condition(Column("project_id"), Op.IN, project_ids),
            Condition(Column("release"), Op.IN, release_versions),
        ],
    )
    request = Request(
        dataset="sessions",
        app_id="default",
        query=query,
        tenant_ids={"organization_id": organization_id},
    )
    data = snuba.raw_snql_query(request, "snuba.sessions.check_releases_have_health_data")["data"]
    return {row["release"] for row in data}


def _get_project_releases_by_stability(
    project_ids,
    offset,
    limit,
    scope,
    stats_period=None,
    environments=None,
    now=None,
):
    """Given some project IDs returns adoption rates that should be updated
    on the postgres tables.
    """
    if stats_period is None:
        stats_period = "24h"

    # Special rule that we support sorting by the last 24h only.
    if scope.endswith("_24h"):
        scope = scope[:-4]
        stats_period = "24h"

    _, stats_start, _ = get_rollup_starts_and_buckets(stats_period, now=now)

    orderby = {
        "crash_free_sessions": [["-divide", ["sessions_crashed", "sessions"]]],
        "crash_free_users": [["-divide", ["users_crashed", "users"]]],
        "sessions": ["-sessions"],
        "users": ["-users"],
    }[scope]

    # Partial tiebreaker to make comparisons in the release-health duplex
    # backend more likely to succeed. A perfectly stable sorting would need to
    # additionally sort by `release`, however in the metrics backend we can't
    # sort by that the same way as in the sessions backend.
    orderby.extend(["-project_id"])

    conditions = []
    if environments is not None:
        conditions.append(["environment", "IN", environments])
    filter_keys = {"project_id": project_ids}
    rv = []

    # Filter out releases with zero users when sorting by either `users` or `crash_free_users`
    having_dict = {}
    if scope in ["users", "crash_free_users"]:
        having_dict["having"] = [["users", ">", 0]]

    for x in raw_query(
        dataset=Dataset.Sessions,
        selected_columns=["project_id", "release"],
        groupby=["release", "project_id"],
        orderby=orderby,
        start=stats_start,
        offset=offset,
        limit=limit,
        conditions=conditions,
        **having_dict,
        filter_keys=filter_keys,
        referrer="sessions.stability-sort",
    )["data"]:
        rv.append((x["project_id"], x["release"]))

    return rv


def _get_project_releases_count(
    organization_id: int,
    project_ids: Sequence[int],
    scope: str,
    stats_period: Optional[str] = None,
    environments: Optional[Sequence[str]] = None,
) -> int:
    """
    Fetches the total count of releases/project combinations
    """
    if stats_period is None:
        stats_period = "24h"

    # Special rule that we support sorting by the last 24h only.
    if scope.endswith("_24h"):
        stats_period = "24h"

    _, stats_start, _ = get_rollup_starts_and_buckets(stats_period)

    where = [
        Condition(Column("started"), Op.GTE, stats_start),
        Condition(Column("started"), Op.LT, datetime.now()),
        Condition(Column("project_id"), Op.IN, project_ids),
        Condition(Column("org_id"), Op.EQ, organization_id),
    ]
    if environments is not None:
        where.append(Condition(Column("environment"), Op.IN, environments))

    having = []
    # Filter out releases with zero users when sorting by either `users` or `crash_free_users`
    if scope in ["users", "crash_free_users"]:
        having.append(Condition(Column("users"), Op.GT, 0))

    query = Query(
        match=Entity("sessions"),
        select=[Function("uniqExact", [Column("release"), Column("project_id")], alias="count")],
        where=where,
        having=having,
    )
    request = Request(
        dataset="sessions",
        app_id="default",
        query=query,
        tenant_ids={"organization_id": organization_id},
    )
    data = snuba.raw_snql_query(request, "snuba.sessions.get_project_releases_count")["data"]
    return data[0]["count"] if data else 0


def _make_stats(start, rollup, buckets, default=0):
    rv = []
    start = int(to_timestamp(start) // rollup + 1) * rollup
    for x in range(buckets):
        rv.append([start, default])
        start += rollup
    return rv


STATS_PERIODS = {
    "1h": (3600, 1),
    "24h": (3600, 24),
    "1d": (3600, 24),
    "48h": (3600, 48),
    "2d": (3600, 48),
    "7d": (86400, 7),
    "14d": (86400, 14),
    "30d": (86400, 30),
    "90d": (259200, 30),
}


def get_rollup_starts_and_buckets(period, now=None):
    if period is None:
        return None, None, None
    if period not in STATS_PERIODS:
        raise TypeError("Invalid stats period")
    seconds, buckets = STATS_PERIODS[period]
    if now is None:
        now = datetime.now(timezone.utc)
    start = now - timedelta(seconds=seconds * buckets)
    return seconds, start, buckets


def _get_release_adoption(project_releases, environments=None, now=None):
    """Get the adoption of the last 24 hours (or a difference reference timestamp)."""
    conditions, filter_keys = _get_conditions_and_filter_keys(project_releases, environments)
    if now is None:
        now = datetime.now(timezone.utc)
    start = now - timedelta(days=1)

    total_conditions = []
    if environments is not None:
        total_conditions.append(["environment", "IN", environments])

    # Users Adoption
    total_users = {}
    # Session Adoption
    total_sessions = {}

    for x in raw_query(
        dataset=Dataset.Sessions,
        selected_columns=["project_id", "users", "sessions"],
        groupby=["project_id"],
        start=start,
        conditions=total_conditions,
        filter_keys=filter_keys,
        referrer="sessions.release-adoption-total-users-and-sessions",
    )["data"]:
        total_users[x["project_id"]] = x["users"]
        total_sessions[x["project_id"]] = x["sessions"]

    rv = {}
    for x in raw_query(
        dataset=Dataset.Sessions,
        selected_columns=["release", "project_id", "users", "sessions"],
        groupby=["release", "project_id"],
        start=start,
        conditions=conditions,
        filter_keys=filter_keys,
        referrer="sessions.release-adoption-list",
    )["data"]:
        # Users Adoption
        total_users_count = total_users.get(x["project_id"])

        users_adoption = None
        if total_users_count:
            users_adoption = float(x["users"]) / total_users_count * 100

        # Sessions Adoption
        total_sessions_count = total_sessions.get(x["project_id"])

        sessions_adoption = None
        if total_sessions_count:
            sessions_adoption = float(x["sessions"] / total_sessions_count * 100)

        rv[x["project_id"], x["release"]] = {
            "adoption": users_adoption,
            "sessions_adoption": sessions_adoption,
            "users_24h": x["users"],
            "sessions_24h": x["sessions"],
            "project_users_24h": total_users_count,
            "project_sessions_24h": total_sessions_count,
        }

    return rv


def extract_duration_quantiles(raw_stats):
    if len(raw_stats["duration_quantiles"]) == 2:
        return {
            "duration_p50": _convert_duration(raw_stats["duration_quantiles"][0]),
            "duration_p90": _convert_duration(raw_stats["duration_quantiles"][1]),
        }

    else:
        return {
            "duration_p50": _convert_duration(raw_stats["duration_quantiles"][0]),
            "duration_p90": _convert_duration(raw_stats["duration_quantiles"][2]),
        }


def _get_release_health_data_overview(
    project_releases,
    environments=None,
    summary_stats_period=None,
    health_stats_period=None,
    stat=None,
    now=None,
):
    """Checks quickly for which of the given project releases we have
    health data available.  The argument is a tuple of `(project_id, release_name)`
    tuples.  The return value is a set of all the project releases that have health
    data.
    """
    if stat is None:
        stat = "sessions"
    assert stat in ("sessions", "users")

    _, summary_start, _ = get_rollup_starts_and_buckets(summary_stats_period or "24h", now=now)
    conditions, filter_keys = _get_conditions_and_filter_keys(project_releases, environments)

    stats_rollup, stats_start, stats_buckets = get_rollup_starts_and_buckets(
        health_stats_period, now=now
    )

    missing_releases = set(project_releases)
    rv = {}
    for x in raw_query(
        dataset=Dataset.Sessions,
        selected_columns=[
            "release",
            "project_id",
            "duration_quantiles",
            "sessions",
            "sessions_errored",
            "sessions_crashed",
            "sessions_abnormal",
            "users",
            "users_crashed",
        ],
        groupby=["release", "project_id"],
        start=summary_start,
        conditions=conditions,
        filter_keys=filter_keys,
        referrer="sessions.release-overview",
    )["data"]:
        rp = {
            "crash_free_users": (
                100 - x["users_crashed"] / float(x["users"]) * 100 if x["users"] else None
            ),
            "crash_free_sessions": (
                100 - x["sessions_crashed"] / float(x["sessions"]) * 100 if x["sessions"] else None
            ),
            "total_users": x["users"],
            "total_sessions": x["sessions"],
            "sessions_crashed": x["sessions_crashed"],
            "sessions_errored": max(
                0, x["sessions_errored"] - x["sessions_crashed"] - x["sessions_abnormal"]
            ),
            "has_health_data": True,
        }
        rp.update(extract_duration_quantiles(x))
        if health_stats_period:
            rp["stats"] = {
                health_stats_period: _make_stats(stats_start, stats_rollup, stats_buckets)
            }
        rv[x["project_id"], x["release"]] = rp
        missing_releases.discard((x["project_id"], x["release"]))

    # Add releases without data points
    if missing_releases:
        # If we're already looking at a 90 day horizon we don't need to
        # fire another query, we can already assume there is no data.
        if summary_stats_period != "90d":
            has_health_data = release_health.check_has_health_data(missing_releases)
        else:
            has_health_data = ()
        for key in missing_releases:
            rv[key] = {
                "duration_p50": None,
                "duration_p90": None,
                "crash_free_users": None,
                "crash_free_sessions": None,
                "total_users": 0,
                "total_sessions": 0,
                "sessions_crashed": 0,
                "sessions_errored": 0,
                "has_health_data": key in has_health_data,
            }
            if health_stats_period:
                rv[key]["stats"] = {
                    health_stats_period: _make_stats(stats_start, stats_rollup, stats_buckets)
                }

    release_adoption = release_health.get_release_adoption(project_releases, environments)
    for key in rv:
        adoption_info = release_adoption.get(key) or {}
        rv[key]["adoption"] = adoption_info.get("adoption")
        rv[key]["sessions_adoption"] = adoption_info.get("sessions_adoption")
        rv[key]["total_users_24h"] = adoption_info.get("users_24h")
        rv[key]["total_project_users_24h"] = adoption_info.get("project_users_24h")
        rv[key]["total_sessions_24h"] = adoption_info.get("sessions_24h")
        rv[key]["total_project_sessions_24h"] = adoption_info.get("project_sessions_24h")

    if health_stats_period:
        for x in raw_query(
            dataset=Dataset.Sessions,
            selected_columns=["release", "project_id", "bucketed_started", stat],
            groupby=["release", "project_id", "bucketed_started"],
            rollup=stats_rollup,
            start=stats_start,
            conditions=conditions,
            filter_keys=filter_keys,
            referrer="sessions.release-stats",
        )["data"]:
            time_bucket = int(
                (parse_snuba_datetime(x["bucketed_started"]) - stats_start).total_seconds()
                / stats_rollup
            )
            key = (x["project_id"], x["release"])
            # Sometimes this might return a release we haven't seen yet or it might
            # return a time bucket that did not exist yet at the time of the initial
            # query.  In that case, just skip it.
            if key in rv and time_bucket < len(rv[key]["stats"][health_stats_period]):
                rv[key]["stats"][health_stats_period][time_bucket][1] = x[stat]

    return rv


def _get_crash_free_breakdown(project_id, release, start, environments=None, now=None):
    filter_keys = {"project_id": [project_id]}
    conditions = [["release", "=", release]]
    if environments is not None:
        conditions.append(["environment", "IN", environments])

    if now is None:
        now = datetime.now(timezone.utc)

    def _query_stats(end):
        row = raw_query(
            dataset=Dataset.Sessions,
            selected_columns=["users", "users_crashed", "sessions", "sessions_crashed"],
            end=end,
            start=start,
            conditions=conditions,
            filter_keys=filter_keys,
            referrer="sessions.crash-free-breakdown",
        )["data"][0]
        return {
            "date": end,
            "total_users": row["users"],
            "crash_free_users": 100 - row["users_crashed"] / float(row["users"]) * 100
            if row["users"]
            else None,
            "total_sessions": row["sessions"],
            "crash_free_sessions": 100 - row["sessions_crashed"] / float(row["sessions"]) * 100
            if row["sessions"]
            else None,
        }

    last = None
    rv = []
    for offset in (
        timedelta(days=1),
        timedelta(days=2),
        timedelta(days=7),
        timedelta(days=14),
        timedelta(days=30),
    ):
        try:
            item_start = start + offset
            if item_start > now:
                if last is None or (item_start - last).days > 1:
                    rv.append(_query_stats(now))
                break
            rv.append(_query_stats(item_start))
            last = item_start
        except QueryOutsideRetentionError:
            # cannot query for these
            pass

    return rv


def _get_project_release_stats(project_id, release, stat, rollup, start, end, environments=None):
    assert stat in ("users", "sessions")

    # since snuba end queries are exclusive of the time and we're bucketing to
    # a full hour, we need to round to the next hour since snuba is exclusive
    # on the end.
    end = to_datetime((to_timestamp(end) // DATASET_BUCKET + 1) * DATASET_BUCKET)

    filter_keys = {"project_id": [project_id]}
    conditions = [["release", "=", release]]
    if environments is not None:
        conditions.append(["environment", "IN", environments])

    buckets = int((end - start).total_seconds() / rollup)
    stats = _make_stats(start, rollup, buckets, default=None)

    # Due to the nature of the probabilistic data structures some
    # subtractions can become negative.  As such we're making sure a number
    # never goes below zero to avoid confusion.

    totals = {
        stat: 0,
        stat + "_healthy": 0,
        stat + "_crashed": 0,
        stat + "_abnormal": 0,
        stat + "_errored": 0,
    }

    for rv in raw_query(
        dataset=Dataset.Sessions,
        selected_columns=[
            "bucketed_started",
            stat,
            stat + "_crashed",
            stat + "_abnormal",
            stat + "_errored",
            "duration_quantiles",
        ],
        groupby=["bucketed_started"],
        start=start,
        end=end,
        rollup=rollup,
        conditions=conditions,
        filter_keys=filter_keys,
        referrer="sessions.release-stats-details",
    )["data"]:
        ts = parse_snuba_datetime(rv["bucketed_started"])
        bucket = int((ts - start).total_seconds() / rollup)
        stats[bucket][1] = {
            stat: rv[stat],
            stat + "_healthy": max(0, rv[stat] - rv[stat + "_errored"]),
            stat + "_crashed": rv[stat + "_crashed"],
            stat + "_abnormal": rv[stat + "_abnormal"],
            stat
            + "_errored": max(
                0, rv[stat + "_errored"] - rv[stat + "_crashed"] - rv[stat + "_abnormal"]
            ),
        }
        stats[bucket][1].update(extract_duration_quantiles(rv))

        # Session stats we can sum up directly without another query
        # as the data becomes available.
        if stat == "sessions":
            for k in totals:
                totals[k] += stats[bucket][1][k]

    for idx, bucket in enumerate(stats):
        if bucket[1] is None:
            stats[idx][1] = {
                stat: 0,
                stat + "_healthy": 0,
                stat + "_crashed": 0,
                stat + "_abnormal": 0,
                stat + "_errored": 0,
                "duration_p50": None,
                "duration_p90": None,
            }

    # For users we need a secondary query over the entire time range
    if stat == "users":
        rows = raw_query(
            dataset=Dataset.Sessions,
            selected_columns=["users", "users_crashed", "users_abnormal", "users_errored"],
            start=start,
            end=end,
            conditions=conditions,
            filter_keys=filter_keys,
            referrer="sessions.crash-free-breakdown-users",
        )["data"]
        if rows:
            rv = rows[0]
            totals = {
                "users": rv["users"],
                "users_healthy": max(0, rv["users"] - rv["users_errored"]),
                "users_crashed": rv["users_crashed"],
                "users_abnormal": rv["users_abnormal"],
                "users_errored": max(
                    0, rv["users_errored"] - rv["users_crashed"] - rv["users_abnormal"]
                ),
            }

    return stats, totals


def _get_release_sessions_time_bounds(project_id, release, org_id, environments=None):
    """
    Get the sessions time bounds in terms of when the first session started and
    when the last session started according to a specific (project_id, org_id, release, environments)
    combination
    Inputs:
        * project_id
        * release
        * org_id: Organisation Id
        * environments
    Return:
        Dictionary with two keys "sessions_lower_bound" and "sessions_upper_bound" that
    correspond to when the first session occurred and when the last session occurred respectively
    """

    def iso_format_snuba_datetime(date):
        return datetime.strptime(date, "%Y-%m-%dT%H:%M:%S+00:00").isoformat()[:19] + "Z"

    release_sessions_time_bounds = {
        "sessions_lower_bound": None,
        "sessions_upper_bound": None,
    }

    filter_keys = {"project_id": [project_id], "org_id": [org_id]}
    conditions = [["release", "=", release]]
    if environments is not None:
        conditions.append(["environment", "IN", environments])

    rows = raw_query(
        dataset=Dataset.Sessions,
        selected_columns=["first_session_started", "last_session_started"],
        aggregations=[
            ["min(started)", None, "first_session_started"],
            ["max(started)", None, "last_session_started"],
        ],
        conditions=conditions,
        filter_keys=filter_keys,
        referrer="sessions.release-sessions-time-bounds",
    )["data"]

    formatted_unix_start_time = datetime.utcfromtimestamp(0).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    if rows:
        rv = rows[0]

        # This check is added because if there are no sessions found, then the
        # aggregations query return both the sessions_lower_bound and the
        # sessions_upper_bound as `0` timestamp and we do not want that behaviour
        # by default
        # P.S. To avoid confusion the `0` timestamp which is '1970-01-01 00:00:00'
        # is rendered as '0000-00-00 00:00:00' in clickhouse shell
        if set(rv.values()) != {formatted_unix_start_time}:
            release_sessions_time_bounds = {
                "sessions_lower_bound": iso_format_snuba_datetime(rv["first_session_started"]),
                "sessions_upper_bound": iso_format_snuba_datetime(rv["last_session_started"]),
            }
    return release_sessions_time_bounds


def __get_crash_free_rate_data(project_ids, start, end, rollup):
    """
    Helper function that executes a snuba query on project_ids to fetch the number of crashed
    sessions and total sessions and returns the crash free rate for those project_ids.
    Inputs:
        * project_ids
        * start
        * end
        * rollup
    Returns:
        Snuba query results
    """
    return raw_query(
        dataset=Dataset.Sessions,
        selected_columns=[
            "project_id",
            "sessions_crashed",
            "sessions_errored",
            "sessions_abnormal",
            "sessions",
        ],
        filter_keys={"project_id": project_ids},
        start=start,
        end=end,
        rollup=rollup,
        groupby=["project_id"],
        referrer="sessions.totals",
    )["data"]


def get_current_and_previous_crash_free_rates(
    project_ids, current_start, current_end, previous_start, previous_end, rollup
):
    """
    Function that returns `currentCrashFreeRate` and the `previousCrashFreeRate` of projects
    based on the inputs provided
    Inputs:
        * project_ids
        * current_start: start interval of currentCrashFreeRate
        * current_end: end interval of currentCrashFreeRate
        * previous_start: start interval of previousCrashFreeRate
        * previous_end: end interval of previousCrashFreeRate
        * rollup
    Returns:
        A dictionary of project_id as key and as value the `currentCrashFreeRate` and the
        `previousCrashFreeRate`

        As an example:
        {
            1: {
                "currentCrashFreeRate": 100,
                "previousCrashFreeRate": 66.66666666666667
            },
            2: {
                "currentCrashFreeRate": 50.0,
                "previousCrashFreeRate": None
            },
            ...
        }
    """
    projects_crash_free_rate_dict = {
        prj: {"currentCrashFreeRate": None, "previousCrashFreeRate": None} for prj in project_ids
    }

    def calculate_crash_free_percentage(row):
        # XXX: Calculation is done in this way to clamp possible negative values and so to calculate
        # crash free rates similar to how it is calculated here
        # Ref: https://github.com/getsentry/sentry/pull/25543
        healthy_sessions = max(row["sessions"] - row["sessions_errored"], 0)
        errored_sessions = max(
            row["sessions_errored"] - row["sessions_crashed"] - row["sessions_abnormal"], 0
        )
        totals = (
            healthy_sessions + errored_sessions + row["sessions_crashed"] + row["sessions_abnormal"]
        )
        try:
            crash_free_rate = 100 - (row["sessions_crashed"] / totals) * 100
        except ZeroDivisionError:
            crash_free_rate = None
        return crash_free_rate

    # currentCrashFreeRate
    current_crash_free_data = __get_crash_free_rate_data(
        project_ids=project_ids,
        start=current_start,
        end=current_end,
        rollup=rollup,
    )
    for row in current_crash_free_data:
        projects_crash_free_rate_dict[row["project_id"]].update(
            {"currentCrashFreeRate": calculate_crash_free_percentage(row)}
        )

    # previousCrashFreeRate
    previous_crash_free_data = __get_crash_free_rate_data(
        project_ids=project_ids,
        start=previous_start,
        end=previous_end,
        rollup=rollup,
    )
    for row in previous_crash_free_data:
        projects_crash_free_rate_dict[row["project_id"]].update(
            {"previousCrashFreeRate": calculate_crash_free_percentage(row)}
        )
    return projects_crash_free_rate_dict


def _get_project_sessions_count(
    project_id: int,
    rollup: int,  # rollup in seconds
    start: datetime,
    end: datetime,
    environment_id: Optional[int] = None,
) -> int:
    filters = {"project_id": [project_id]}
    if environment_id:
        filters["environment"] = [environment_id]

    result_totals = raw_query(
        selected_columns=["sessions"],
        rollup=rollup,
        dataset=Dataset.Sessions,
        start=start,
        end=end,
        filter_keys=filters,
        referrer="sessions.get_project_sessions_count",
    )["data"]

    return result_totals[0]["sessions"] if result_totals else 0


def _get_num_sessions_per_project(
    project_ids: Sequence[int],
    start: datetime,
    end: datetime,
    environment_ids: Optional[Sequence[int]] = None,
    rollup: Optional[int] = None,  # rollup in seconds
) -> Sequence[Tuple[int, int]]:

    filters = {"project_id": list(project_ids)}

    if environment_ids:
        filters["environment"] = environment_ids

    result_totals = raw_query(
        selected_columns=["sessions"],
        dataset=Dataset.Sessions,
        start=start,
        end=end,
        filter_keys=filters,
        groupby=["project_id"],
        referrer="sessions.get_num_sessions_per_project",
        rollup=rollup,
    )

    ret_val = []
    for data in result_totals["data"]:
        ret_val.append((data["project_id"], data["sessions"]))
    return ret_val
