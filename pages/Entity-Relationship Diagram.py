import streamlit as st

from db.connection import run_query

ERD_URL = 'https://dbdiagram.io/e/6ab5ea900f25a52d010271f5/6abead110f25a52d016885fb'

# The diagram is hosted on another site, so Streamlit can't wait for it before
# rendering. Wrap it in a local document that shows a spinner until it loads.
ERD_HTML = f"""<!doctype html>
<html>
<head>
<style>
  html, body {{ height: 100%; margin: 0; background: #0E1117; overflow: hidden; }}
  #loading {{
    position: absolute; inset: 0; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 12px;
    color: #FAFAFA; font-family: "Source Sans Pro", sans-serif;
  }}
  #spinner {{
    width: 36px; height: 36px; border-radius: 50%;
    border: 4px solid #31333F; border-top-color: #FF4B4B;
    animation: spin 0.8s linear infinite;
  }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  iframe {{
    position: absolute; inset: 0; width: 100%; height: 100%; border: 0;
    opacity: 0; transition: opacity 0.3s;
  }}
  iframe.loaded {{ opacity: 1; }}
</style>
</head>
<body>
  <div id="loading"><div id="spinner"></div>Loading diagram...</div>
  <iframe src="{ERD_URL}"
          onload="this.classList.add('loaded'); document.getElementById('loading').remove();"></iframe>
</body>
</html>"""

st.header("Entity-Relationship Diagram")

st.iframe(ERD_HTML, height=400)
