import streamlit as st

from db.queries import player_match_history, player_name, search_players
from ui import require_data

require_data()

query = st.text_input(
    "Player",
    placeholder="e.g. John Doe or 81475894",
    help="A Steam display name (or part of one) or a SteamID3 account ID.",
    key="player",
    bind="query-params",
    width=320,
).strip()

if not query:
    st.info("Search for a player by name or account ID to see their recent matches.", icon=":material/search:")
    st.stop()

labels = {r.account_id: f"{r.account_name} · {r.matches} match{'es' if r.matches != 1 else ''} · ID {r.account_id}"
          for r in search_players(query).itertuples()}
# digits can be an account ID or a name like "777", so offer both
if query.isdigit() and int(query) not in labels and not player_match_history(int(query)).empty:
    labels = {int(query): f"Account ID {query}"} | labels
if not labels:
    st.info(f"No player named like “{query}” in the past week's sampled matches.")
    st.stop()
account_id = (next(iter(labels)) if len(labels) == 1 else
              st.selectbox("Matching players", list(labels), format_func=labels.get, key="player_pick"))

st.subheader(player_name(account_id) or f"Account {account_id}", anchor=False)
st.caption(f"Account ID {account_id}")

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
              chart_data=history["net_worth"].iloc[::-1].tolist() if len(history) > 1 else None, chart_type="line")

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
