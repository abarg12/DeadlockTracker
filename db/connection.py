import streamlit as st

def get_connection():
    return st.get_connection("postgresql", type="sql")