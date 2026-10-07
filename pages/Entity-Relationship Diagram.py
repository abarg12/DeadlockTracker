import streamlit as st

from db.connection import run_query

st.header("Entity-Relationship Diagram")

st.iframe('https://dbdiagram.io/e/6ab5ea900f25a52d010271f5/6abead110f25a52d016885fb')