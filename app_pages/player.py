import streamlit as st

from db.queries import most_active_player, player_match_history
from ui import require_data

require_data()

account_id = st.number_input(
    "Account ID",
    min_value=1,
    value=most_active_player(),
    step=1,
    help="The player's SteamID3. The default is the most active player in the loaded data.",
    key="account_id",
    bind="query-params",
    width=240,
)

history = player_match_history(account_id)
if history.empty:
    st.info("No loaded matches for this account. Only sampled matches from the past week are searchable.")
    st.stop()

wins = int(history["won"].sum())
with st.container(horizontal=True):
    st.metric("Record", f"{wins}W – {len(history) - wins}L", border=True,
              help=f"Over the {len(history)} most recent loaded matches")
    st.metric("Avg K / D / A",
              f"{history['kills'].mean():.1f} / {history['deaths'].mean():.1f} / {history['assists'].mean():.1f}",
              border=True)
    st.metric("Avg souls", f"{history['net_worth'].mean():,.0f}", border=True,
              chart_data=history["net_worth"].iloc[::-1].tolist(), chart_type="line")

history["result"] = history["won"].map({True: "Win", False: "Loss"})
history["duration_min"] = history["duration_s"] / 60
st.dataframe(
    history,
    column_order=["start_time", "result", "hero", "kills", "deaths", "assists", "net_worth", "duration_min",
                  "match_mode", "match_id"],
    column_config={
        "start_time": st.column_config.DatetimeColumn("Started", format="MMM D, h:mm a"),
        "result": "Result",
        "hero": "Hero",
        "kills": "Kills",
        "deaths": "Deaths",
        "assists": "Assists",
        "net_worth": st.column_config.NumberColumn("Souls", format="localized"),
        "duration_min": st.column_config.NumberColumn("Duration (min)", format="%.1f"),
        "match_mode": "Mode",
        "match_id": st.column_config.NumberColumn("Match ID", format="%d"),
    },
    hide_index=True,
)
