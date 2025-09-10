import requests
from bs4 import BeautifulSoup as bs
import pandas as pd
from datetime import datetime
import re
import streamlit as st

LEAGUE_LINKS = {
    "Premier League": "https://onefootball.com/en/competition/premier-league-9/fixtures",
    "Championship": "https://onefootball.com/en/competition/efl-championship-27/fixtures",
    "League 1": "https://onefootball.com/en/competition/efl-league-one-42/fixtures",
    "League 2": "https://onefootball.com/en/competition/efl-league-two-43/fixtures"
}


def parse_date(date_str: str):
    if re.search(r"'|Half time|FT", date_str, re.IGNORECASE):
        return None
    try:
        # Parse but keep naive datetime (interpreted literally)
        return datetime.strptime(date_str.strip(), "%d/%m/%Y%H:%M")
    except Exception:
        return None


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
    card_html = f"""
    <div class="match-card">
        <div style='display:flex; justify-content:space-between; align-items:center;'>
            <div class='team' style='text-align:right;'>{row.Home}</div>
            <div style='text-align:center; flex:1;'>
                <div class='score'>{row.HG} - {row.AG}</div>
                <div class='status'>{emoji} {status}</div>
                <div class='time'>{row.Date_Time}</div>
            </div>
            <div class='team' style='text-align:left;'>{row.Away}</div>
        </div>
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)

