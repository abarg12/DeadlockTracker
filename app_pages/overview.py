import streamlit as st

from db.queries import daily_summary
from ui import data_through_caption, require_data, window_filter

require_data()

since = window_filter()
data_through_caption()

summary = daily_summary(since)
summary["avg_duration_min"] = (summary["avg_duration_s"] / 60).round(1)
total_matches = int(summary["matches"].sum())
avg_duration_min = (summary["matches"] * summary["avg_duration_min"]).sum() / max(total_matches, 1)
# a one-point sparkline is drawn as two identical points, so only show trends across several days
show_trend = len(summary) > 1

with st.container(horizontal=True):
    st.metric(
        "Matches",
        f"{total_matches:,}",
        help="Matches in the sampled data (a few percent of public matches), not every match played",
        border=True,
        chart_data=summary["matches"].tolist() if show_trend else None,
        chart_type="bar",
    )
    st.metric(
        "Average duration",
        f"{avg_duration_min:.1f} min",
        border=True,
        chart_data=summary["avg_duration_min"].tolist() if show_trend else None,
        chart_type="line",
    )
    st.metric("Days covered", len(summary), border=True)

left, right = st.columns(2)
with left.container(border=True):
    st.subheader("Matches per day")
    st.bar_chart(summary, x="match_date", y="matches", x_label="Date (UTC)", y_label="Matches")
with right.container(border=True):
    st.subheader("Average match duration")
    st.line_chart(summary, x="match_date", y="avg_duration_min", x_label="Date (UTC)", y_label="Minutes")
