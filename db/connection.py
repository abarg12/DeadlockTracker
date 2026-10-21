import pandas as pd
import streamlit as st
from sqlalchemy import text


def get_connection():
    return st.connection(
        "postgresql",
        type="sql",
        driver="psycopg2",
        connect_args={"options": "-csearch_path=optimized"},
    )


# runs a sql query and returns a Pandas dataframe of the result
def run_query(sql: str, params: dict | None = None) -> pd.DataFrame:
    engine = get_connection().engine
    with engine.connect() as connection:
        return pd.read_sql(text(sql), connection, params=params or {})
