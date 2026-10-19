import streamlit as st

from db.queries import hero_win_rates
from ui import data_through_caption, match_mode_filter, require_data, window_filter

require_data()

with st.container(horizontal=True, vertical_alignment="bottom"):
    since = window_filter()
    match_mode = match_mode_filter()
    min_games = st.number_input("Minimum games", min_value=1, value=20, step=10, width=160)
data_through_caption()

heroes = hero_win_rates(since, match_mode)
shown = heroes[heroes["games"] >= min_games]

if shown.empty:
    st.info("No hero has that many games in this window. Lower the minimum or widen the window.")
    st.stop()

best = shown.loc[shown["win_rate"].idxmax()]
most_played = shown.loc[shown["games"].idxmax()]
with st.container(horizontal=True):
    st.metric("Heroes shown", len(shown), border=True)
    st.metric("Highest win rate", best["name"], f"{best['win_rate']:.1%}", delta_color="off", delta_arrow="off",
              border=True)
    st.metric("Most played", most_played["name"], f"{int(most_played['games']):,} games", delta_color="off",
              delta_arrow="off", border=True)

with st.container(border=True):
    st.subheader("Win rate by hero")
    st.bar_chart(shown, x="name", y="win_rate", horizontal=True, sort="-win_rate", x_label="Win rate",
                 y_label="", height=max(300, 22 * len(shown)))

st.dataframe(
    shown,
    column_order=["name", "games", "wins", "win_rate", "avg_kills", "avg_deaths", "avg_assists"],
    column_config={
        "name": "Hero",
        "games": st.column_config.NumberColumn("Games", format="localized"),
        "wins": st.column_config.NumberColumn("Wins", format="localized"),
        "win_rate": st.column_config.NumberColumn("Win rate", format="percent"),
        "avg_kills": "Avg kills",
        "avg_deaths": "Avg deaths",
        "avg_assists": "Avg assists",
    },
    hide_index=True,
)
