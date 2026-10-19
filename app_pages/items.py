import streamlit as st

from db.queries import item_win_rates
from ui import data_through_caption, match_mode_filter, require_data, window_filter

require_data()

with st.container(horizontal=True, vertical_alignment="bottom"):
    since = window_filter()
    match_mode = match_mode_filter()
    min_games = st.number_input("Minimum games", min_value=1, value=50, step=50, width=160)
data_through_caption()

items = item_win_rates(since, match_mode)
tiers = sorted(items["item_tier"].dropna().astype(int).unique())
selected_tiers = st.pills("Tier", tiers, selection_mode="multi", default=tiers, format_func=lambda t: f"Tier {t}")

shown = items[(items["games"] >= min_games) & items["item_tier"].isin(selected_tiers)]
if shown.empty:
    st.info("No item matches these filters. Lower the minimum, pick more tiers, or widen the window.")
    st.stop()

with st.container(border=True):
    st.subheader("Highest win rate items")
    top = shown.nlargest(15, "win_rate")
    st.bar_chart(top, x="name", y="win_rate", horizontal=True, sort="-win_rate", x_label="Win rate", y_label="")

st.dataframe(
    shown,
    column_order=["name", "item_tier", "cost", "games", "wins", "win_rate"],
    column_config={
        "name": "Item",
        "item_tier": st.column_config.NumberColumn("Tier", format="%d"),
        "cost": st.column_config.NumberColumn("Cost (souls)", format="localized"),
        "games": st.column_config.NumberColumn(
            "Games", format="localized", help="Games in which a player bought the item (rebuys count once)"
        ),
        "wins": st.column_config.NumberColumn("Wins", format="localized"),
        "win_rate": st.column_config.NumberColumn("Win rate", format="percent"),
    },
    hide_index=True,
)
