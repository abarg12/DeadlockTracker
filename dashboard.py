import streamlit as st

st.set_page_config(page_title="Deadlock Tracker", layout="wide")
st.set_option("client.toolbarMode", "viewer")
st.html("""<style>
.stAppHeader { height: 1rem; }
[data-testid="stTopNavSection"] { font-size: 1rem; padding: 0.25rem 1rem; }
.stMainBlockContainer { padding-top: 3rem; }
</style>""")

page = st.navigation(
    {
        "Stats": [
            st.Page("app_pages/overview.py", title="Overview", icon=":material/dashboard:"),
            st.Page("app_pages/heroes.py", title="Heroes", icon=":material/groups:"),
            st.Page("app_pages/items.py", title="Items", icon=":material/shopping_cart:"),
            st.Page("app_pages/player.py", title="Player history", icon=":material/person_search:"),
        ],
        "Database": [
            st.Page("app_pages/er_diagram.py", title="E-R diagram", icon=":material/schema:"),
            st.Page("app_pages/query_explorer.py", title="Query explorer", icon=":material/terminal:"),
        ],
    },
    position="top",
)

st.title(page.title, icon=page.icon, anchor=False)
page.run()
