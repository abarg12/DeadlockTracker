import streamlit as st

from db.connection import run_query

st.header("Overview")

tables_df = run_query(
    """
    SELECT table_name
    FROM information_schema.tables
    WHERE table_schema = 'public'
    ORDER BY table_name
    """
)
st.subheader("Tables")
st.dataframe(tables_df, width="stretch")