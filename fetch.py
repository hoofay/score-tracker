import requests
from bs4 import BeautifulSoup as bs
import pandas as pd
from datetime import datetime
import re
import streamlit as st
import pytz

LEAGUE_LINKS = {
    "Premier League": "https://onefootball.com/en/competition/premier-league-9/fixtures",
    "Championship": "https://onefootball.com/en/competition/efl-championship-27/fixtures",
    "League 1": "https://onefootball.com/en/competition/efl-league-one-42/fixtures",
    "League 2": "https://onefootball.com/en/competition/efl-league-two-43/fixtures"
}

uk_tz = pytz.timezone("Europe/London")

# fetch.py (replace parse_date)
from datetime import datetime
from dateutil import parser as dtparser
import pytz
import re

uk_tz = pytz.timezone("Europe/London")

def parse_date(date_str: str):
    """Parse a scraped date/time string into Europe/London tz."""
    if not date_str or re.search(r"'|Half time|FT|Live", date_str, re.IGNORECASE):
        return None
    try:
        # Fix formatting issue: ensure space between date and time
        fixed = re.sub(r"^(\d{2}/\d{2}/\d{4})(\d{2}:\d{2})$", r"\1 \2", date_str.strip())
        dt = dtparser.parse(fixed, dayfirst=True)
    except Exception:
        return None

    if dt.tzinfo is None:
        dt = uk_tz.localize(dt)
    else:
        dt = dt.astimezone(uk_tz)

    return dt


def fetch_matches():
    """
    Scrape fixtures and results for the four English leagues.
    Returns a DataFrame with columns:
    [Competition, Home, Away, HG, AG, Date_Time, ParsedDate].
    If scraping fails, raises a RuntimeError.
    """
    df = pd.DataFrame(columns=["Competition", "Home", "Away", "HG", "AG", "Date_Time", "ParsedDate"])
    errors = []

    for league, link in LEAGUE_LINKS.items():
        try:
            source = requests.get(link, timeout=10).text
            page = bs(source, "lxml")

            # Extract match times
            dateTime = [x.text.strip() for x in page.find_all(
                "div", class_="SimpleMatchCard_simpleMatchCard__matchContent__prwTf")]

            # Extract teams
            teams = [x.text.strip() for x in page.find_all(
                "span", class_="SimpleMatchCardTeam_simpleMatchCardTeam__name__7Ud8D")]
            home = teams[0::2]
            away = teams[1::2]

            # Extract scores
            scores = [x.text.split() for x in page.find_all(
                "span", class_="SimpleMatchCardTeam_simpleMatchCardTeam__score__UYMc_")]
            home_scores = [s[0] if s else "-" for s in scores[0::2]]
            away_scores = [s[0] if s else "-" for s in scores[1::2]]

            # Parse dates
            parsed = [parse_date(dt) for dt in dateTime]

            # Append to DataFrame
            df = pd.concat([df, pd.DataFrame({
                "Competition": league,
                "Home": home,
                "Away": away,
                "HG": home_scores,
                "AG": away_scores,
                "Date_Time": dateTime,
                "ParsedDate": parsed
            })], ignore_index=True)

        except Exception as e:
            errors.append(f"{league}: {e}")

    if errors:
        raise RuntimeError(" | ".join(errors))

    # convert None -> pd.NaT, then to datetime
    df['ParsedDate'] = pd.to_datetime(df['ParsedDate'], errors='coerce')
    
    # If tz-naive -> localize; if tz-aware -> convert to Europe/London
    try:
        current_tz = df['ParsedDate'].dt.tz
    except Exception:
        current_tz = None
    
    if current_tz is None:
        # tz-naive, localize
        df['ParsedDate'] = df['ParsedDate'].dt.tz_localize('Europe/London')
    else:
        # tz-aware, convert to London (this also handles UTC -> Europe/London)
        df['ParsedDate'] = df['ParsedDate'].dt.tz_convert('Europe/London')

    return df


def get_status(row):
    """Return (status, emoji) for a match row."""
    if row.HG != "-" and row.AG != "-":
        return "Finished", "🔵"
    elif "'" in row.Date_Time or "Half time" in row.Date_Time:
        return "Live", "🟢"
    else:
        return "Upcoming", "⚪"


def build_match_id(row):
    """Create a stable match identifier from row."""
    return f"{row.Home}-vs-{row.Away}_{row.Date_Time}_{row.Competition}"

# --- Helper for Python -> JS toasts ---
def trigger_toast(message: str, toast_type: str = "info"):
    st.markdown(
        f"""
        <script>
        showToast("{message}", "{toast_type}");
        </script>
        """,
        unsafe_allow_html=True
    )

# --- Display match as styled card ---
def display_match(row):
    status, emoji = get_status(row)
    time_str = row.ParsedDate.astimezone(uk_tz).strftime("%b %d, %H:%M") if row.ParsedDate else row.Date_Time
    card_html = f"""
    <div class="match-card">
        <div style='display:flex; justify-content:space-between; align-items:center;'>
            <div class='team' style='text-align:right;'>{row.Home}</div>
            <div style='text-align:center; flex:1;'>
                <div class='score'>{row.HG} - {row.AG}</div>
                <div class='status'>{emoji} {status}</div>
                <div class='time'>{time_str}</div>
            </div>
            <div class='team' style='text-align:left;'>{row.Away}</div>
        </div>
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)







