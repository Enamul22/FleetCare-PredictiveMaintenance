"""Pure table filtering/pagination shared by UI and acceptance tests; no data is silently capped."""

import pandas as pd


def filter_faults(frame, filters):
    f = frame.copy()
    for column in [
        "country",
        "city",
        "code",
        "model_id",
        "severity",
        "fault_status",
        "creation_status",
        "order_status",
        "customer_id",
        "vehicle_id",
    ]:
        value = filters.get(column, "All")
        if value and value != "All":
            f = f[f[column] == value]
    query = filters.get("search", "").strip().casefold()
    if query:
        columns = [
            "fault_id",
            "vehicle_id",
            "customer_id",
            "customer_name",
            "city",
            "country",
            "fault_name",
            "order_id",
        ]
        text = f[columns].fillna("").astype(str).agg(" ".join, axis=1).str.casefold()
        f = f[text.str.contains(query, regex=False)]
    if filters.get("date_from"):
        left = pd.Timestamp(filters["date_from"], tz="UTC")
        # Include any episode intersecting the selected date interval; open/unknown episodes have no end.
        ends = pd.to_datetime(f.ended_at, utc=True)
        f = f[ends.isna() | ends.ge(left)]
    if filters.get("date_to"):
        right = pd.Timestamp(filters["date_to"], tz="UTC") + pd.Timedelta(days=1)
        f = f[pd.to_datetime(f.started_at, utc=True).lt(right)]
    sort = filters.get("sort", "Newest detection")
    if sort == "Severity":
        f = (
            f.assign(_severity=f.severity.map({"critical": 0, "warning": 1}))
            .sort_values(["_severity", "confirmed_at", "fault_id"], ascending=[True, False, True])
            .drop(columns="_severity")
        )
    elif sort == "Vehicle":
        f = f.sort_values(["vehicle_id", "confirmed_at", "fault_id"])
    else:
        f = f.sort_values(["confirmed_at", "fault_id"], ascending=[sort == "Oldest detection", True])
    return f.reset_index(drop=True)


def page_slice(frame, page, size):
    pages = max(1, (len(frame) + size - 1) // size)
    page = max(1, min(int(page), pages))
    return frame.iloc[(page - 1) * size : page * size].reset_index(drop=True), page, pages
