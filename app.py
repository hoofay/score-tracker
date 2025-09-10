import streamlit as st
from fetch import fetch_matches, get_status, build_match_id, LEAGUE_LINKS, display_match
from streamlit_autorefresh import st_autorefresh
from datetime import datetime, timedelta
from collections import defaultdict
import urllib.parse
import pandas as pd
import json
import pytz

uk_tz = pytz.timezone("Europe/London")

st.set_page_config(page_title="Match Tracker", layout="wide")

# 🔄 Auto-refresh every 60 seconds
# st_autorefresh(interval=60000, key="refresh")

# --- Global CSS + Toast System ---
st.markdown("""
    <style>
    #MainMenu, footer, header {visibility: hidden;}

    .stApp {
        background: linear-gradient(135deg, #111827, #0f172a);
        font-family: 'Inter', sans-serif;
        color: #f9fafb;
    }

    /* Match Cards */
    .match-card {
        background: #1e293b;
        padding: 1rem 1.25rem;
        border-radius: 1rem;
        margin-bottom: 1rem;
        box-shadow: 0 4px 12px rgba(0,0,0,0.4);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .match-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 16px rgba(0,0,0,0.6);
    }

    .team { font-weight: 600; font-size: 1.2rem; }
    .score { font-size: 1.6rem; font-weight: bold; margin: 0.25rem 0; }
    .status { font-size: 0.9rem; color: #9ca3af; }
    .time { font-size: 0.8rem; color: #6b7280; }

    .stButton button {
        background: #2563eb;
        color: white;
        border-radius: 0.75rem;
        padding: 0.5rem 1.25rem;
        border: none;
        transition: background 0.2s ease;
    }
    .stButton button:hover { background: #1d4ed8; }

    /* 🔔 Toast System */
    .toast {
        visibility: hidden;
        min-width: 200px;
        margin-left: -100px;
        background-color: #374151;
        color: #fff;
        text-align: center;
        border-radius: 8px;
        padding: 12px 16px;
        position: fixed;
        z-index: 1000;
        left: 50%;
        bottom: 40px;
        font-size: 0.9rem;
        box-shadow: 0 4px 10px rgba(0,0,0,0.4);
        opacity: 0;
        transition: opacity 0.4s, bottom 0.4s;
    }
    .toast.show {
        visibility: visible;
        opacity: 1;
        bottom: 60px;
    }
    .toast-success { background-color: #10b981; }
    .toast-error { background-color: #ef4444; }
    .toast-info { background-color: #3b82f6; }
    </style>

    <div id="toast" class="toast"></div>

    <script>
    function showToast(message, type) {
        let toast = document.getElementById("toast");
        toast.className = "toast toast-" + type + " show";
        toast.innerHTML = message;
        setTimeout(function(){ toast.className = toast.className.replace("show", ""); }, 2000);
    }
    </script>
""", unsafe_allow_html=True)

from fetch import trigger_toast

# --- Load all matches with error handling ---
try:
    df = fetch_matches()
    if st.session_state.get("fetch_error"):
        trigger_toast("✅ Data source recovered", "success")
    st.session_state.fetch_error = None
except RuntimeError as e:
    df = pd.DataFrame(columns=["Competition", "Home", "Away", "HG", "AG", "Date_Time", "ParsedDate"])
    st.session_state.fetch_error = str(e)

# --- Show persistent error toast after each refresh if scraping failed ---
if st.session_state.get("fetch_error"):
    trigger_toast(f"❌ Failed to fetch matches: {st.session_state.fetch_error}", "error")

# --- Query params ---
params = st.query_params
selected_matches = params.get("matches", [])

if selected_matches:
    selected_matches = selected_matches.split(",")

# --- Initialize session state ---
if 'selected_matches_temp' not in st.session_state:
    if selected_matches:
        st.session_state.selected_matches_temp = selected_matches
    else:
        st.session_state.selected_matches_temp = []


# --- Selection Mode ---
if not selected_matches:
    st.header("Select Matches to Track")
    st.info("Pick up to 10 upcoming matches to track from the following list")

    today = datetime.now(uk_tz)
    cutoff_max = today + timedelta(days=4)
    cutoff_min = today - timedelta(days=1)
    
    candidates = df[(df["ParsedDate"].notna()) & (df["ParsedDate"] <= cutoff_max) & (df["ParsedDate"] >= cutoff_min)]
    candidates = candidates.sort_values("ParsedDate")
    
    # Build human-readable labels + mapping to match IDs
    label_to_id = {}
    options = []
    for _, row in candidates.iterrows():
        match_id = build_match_id(row)
        # when building label/date_str
        date_str = row.ParsedDate.astimezone(uk_tz).strftime("%b %d, %H:%M") if pd.notna(row.ParsedDate) else "TBD"
        label = f"{row.Home} vs {row.Away} | {date_str} | {row.Competition}"
        options.append(label)
        label_to_id[label] = match_id

    selected_labels = st.multiselect(
        "Choose matches:",
        options=options,
        default=[label for label, mid in label_to_id.items() if mid in st.session_state.selected_matches_temp],
        max_selections=10
    )

    # Map back to match IDs
    st.session_state.selected_matches_temp = [label_to_id[label] for label in selected_labels]

    # Generate shareable link
    if st.button("Generate Shareable Link") and st.session_state.selected_matches_temp:
        params = {"matches": ",".join(st.session_state.selected_matches_temp)}
        page_url = "https://score-tracker.streamlit.app/"  # Replace with deployed URL
        query_string = urllib.parse.urlencode(params)
        shareable_url = f"{page_url}?{query_string}"

        # Escape for JS
        shareable_url_js = json.dumps(shareable_url)
    
        # Trigger toast to indicate link generation
        trigger_toast("✅ Link generated!", "success")

        # Render link + copy button with safe JS
        st.markdown(f"""
            <div style="display:flex; align-items:center; gap:10px; margin-top:10px;">
                <a href={shareable_url_js} target="_blank" style="
                    color:#3b82f6; 
                    font-weight:600; 
                    text-decoration:none;
                    ">🔗 Open Shareable Link</a>
            </div>
        """, unsafe_allow_html=True)

# --- Display Mode ---
else:
    st.header("Match Tracker")

    auto_refresh = st.checkbox("Enable auto-refresh", value=False)
    if auto_refresh:
        st_autorefresh(interval=60000, key="refresh")

    display_rows = []
    for match_id in st.session_state.selected_matches_temp:
        try:
            parts = match_id.split("_")
            if len(parts) < 3:
                trigger_toast(f"⚠️ Invalid match ID skipped: {match_id}", "error")
                continue
            home, away = parts[0].split("-vs-")
            parsed_date_str, comp = parts[1], parts[2]
    
            # convert back to datetime
            try:
                parsed_date = pd.to_datetime(parsed_date_str)
            except Exception:
                parsed_date = None
    
            match = df[
                (df.Home == home) &
                (df.Away == away) &
                (df.ParsedDate == parsed_date) &
                (df.Competition == comp)
            ]

            if not match.empty:
                display_rows.append(match.iloc[0])
            else:
                trigger_toast(f"⚠️ Match not found: {match_id}", "error")
    
        except Exception:
            trigger_toast(f"❌ Error parsing {match_id}", "error")

    grouped = defaultdict(list)
    for row in display_rows:
        grouped[row.Competition].append(row)

    for comp in LEAGUE_LINKS.keys():
        if comp not in grouped:
            continue
        st.subheader(f"🏆 {comp}")
        matches = sorted(
            grouped[comp],
            key=lambda r: (r.ParsedDate if r.ParsedDate is not None else datetime.max)
        )
        for row in matches:
            display_match(row)




















