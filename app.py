import streamlit as st
from db.queries import *

st.set_page_config(page_title="Deadlock Tracker", layout="wide")
st.title("Deadlock Tracker")
st.set_option("client.toolbarMode", "viewer")
