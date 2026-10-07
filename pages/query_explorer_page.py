import streamlit as st

from db.connection import run_query

st.header("Query Explorer")

sql_text = st.text_area(
    "SQL query",
    value=(
        "SELECT h.name, COUNT(*) AS games, ROUND(AVG(mp.won::int), 3) AS win_rate\n"
        "FROM match_player mp JOIN hero h USING (hero_id)\n"
        "GROUP BY h.name ORDER BY games DESC;"
    ),
    height=150,
)

if st.button("Run"):
    try:
        result_df = run_query(sql_text)
        st.write(f"{len(result_df)} rows")
        st.dataframe(result_df, width="stretch")
    except Exception as error:
        st.error(str(error))