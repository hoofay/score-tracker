import requests
from bs4 import BeautifulSoup as bs
import pandas as pd
from datetime import datetime
import re
import streamlit as st
import pytz
from dateutil import parser as dtparser

# --- League links ---
FIXTURE_LINKS = {
    "Premier League": "https://onefootball.com/en/competition/premier-league-9/fixtures",
    "Championship": "https://onefootball.com/en/competition/efl-championship-27/fixtures",
    "League 1": "https://onefootball.com/en/competition/efl-league-one-42/fixtures",
    "League 2": "https://onefootball.com/en/competition/efl-league-two-43/fixtures"
}

RESULT_LINKS = {
    "Premier League": "https://onefootball.com/en/competition/premier-league-9/results",
    "Championship": "https://onefootball.com/en/competition/efl-championship-27/results",
    "League 1": "https://onefootball.com/en/competition/efl-league-one-42/results",
    "League 2": "https://onefootball.com/en/competition/efl-league-two-43/results"
}

# --- Timezones ---
uk_tz = pytz.timezone("Europe/London")
us_tz = pytz.timezone("US/Eastern")  # server timezone

# --- Regex for ISO and epoch ---
ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?(?:Z|[+-]\d{2}:?\d{2})?")
EPOCH_RE = re.compile(r"\b\d{10,13}\b")

# --- Timestamp parsing ---
def parse_timestamp(val: str, source_tz=us_tz):
    """
    Parse a timestamp string (ISO, epoch, or free-text) and convert to Europe/London.
    Assumes tz-naive timestamps are in source_tz (US server timezone).
    Returns tz-aware datetime in UK time or None.
    """
    if not val:
        return None
    val = val.strip()

    # 1) ISO format
    m_iso = ISO_RE.search(val)
    if m_iso:
        try:
            dt = dtparser.isoparse(m_iso.group(0))
            if dt.tzinfo is None:
                dt = source_tz.localize(dt)
            dt = dt.astimezone(uk_tz)
            return dt
        except Exception:
            pass

    # 2) Epoch format
    m_epoch = EPOCH_RE.search(val)
    if m_epoch:
        try:
            ep = int(m_epoch.group(0))
            if len(m_epoch.group(0)) == 13:
                ep = ep / 1000.0
            dt = datetime.fromtimestamp(ep, tz=pytz.UTC)
            dt = dt.astimezone(uk_tz)
            return dt
        except Exception:
            pass

    # 3) Free-text date
    try:
        dt = dtparser.parse(val, fuzzy=True)
        if dt.tzinfo is None:
            dt = source_tz.localize(dt)
        dt = dt.astimezone(uk_tz)
        return dt
    except Exception:
        return None

# --- Extract timestamp from HTML element ---
def extract_timestamp_from_element(el, source_tz=us_tz):
    """
    Look for timestamps in common HTML attributes, child elements, or inner text.
    Returns tz-aware Europe/London datetime or None.
    """
    if el is None:
        return None

    candidate_attrs = [
        "datetime", "data-utc", "data-timestamp", "data-date", "data-time",
        "data-start", "data-unixtime", "data-unix", "data-unixtimestamp",
        "data-epoch", "data-timestring", "data-datetime", "data-start-date"
    ]

    # 1) Attributes
    for a in candidate_attrs:
        if el.has_attr(a):
            dt = parse_timestamp(el[a], source_tz=source_tz)
            if dt:
                return dt

    # 2) <time> tag
    time_tag = el.find("time")
    if time_tag and time_tag.has_attr("datetime"):
        dt = parse_timestamp(time_tag["datetime"], source_tz=source_tz)
        if dt:
            return dt

    # 3) Child elements
    for child in el.find_all(True, recursive=True):
        for attr, val in child.attrs.items():
            if isinstance(val, list):
                val = " ".join(val)
            if isinstance(val, str) and val.strip():
                dt = parse_timestamp(val, source_tz=source_tz)
                if dt:
                    return dt

    # 4) Inner text fallback
    raw_text = el.get_text(" ", strip=True)
    return parse_timestamp(raw_text, source_tz=source_tz)

# --- Fetch matches ---
def fetch_matches(LEAGUE_LINKS):
    """
    Scrape fixtures and results for the four English leagues.
    Returns a DataFrame with columns:
    [Competition, Home, Away, HG, AG, Date_Time, ParsedDate].
    """
    df = pd.DataFrame(columns=["Competition", "Home", "Away", "HG", "AG", "Date_Time", "ParsedDate"])
    errors = []

    for league, link in LEAGUE_LINKS.items():
        try:
            source = requests.get(link, timeout=10).text
            page = bs(source, "lxml")

            # Match times
            date_elements = page.find_all("div", class_="SimpleMatchCard_simpleMatchCard__matchContent__prwTf")
            date_texts = []
            date_parsed = []
            for el in date_elements:
                raw = el.get_text(" ", strip=True)
                parsed = extract_timestamp_from_element(el)
                date_texts.append(raw)
                date_parsed.append(parsed)

            # Teams
            teams = [x.text.strip() for x in page.find_all(
                "span", class_="SimpleMatchCardTeam_simpleMatchCardTeam__name__7Ud8D")]
            home = teams[0::2]
            away = teams[1::2]

            # Scores
            scores = [x.text.split() for x in page.find_all(
                "span", class_="SimpleMatchCardTeam_simpleMatchCardTeam__score__UYMc_")]
            home_scores = [s[0] if s else "-" for s in scores[0::2]]
            away_scores = [s[0] if s else "-" for s in scores[1::2]]

            # Build DataFrame
            df = pd.concat([df, pd.DataFrame({
                "Competition": league,
                "Home": home,
                "Away": away,
                "HG": home_scores,
                "AG": away_scores,
                "Date_Time": date_texts,
                "ParsedDate": date_parsed
            })], ignore_index=True)

        except Exception as e:
            errors.append(f"{league}: {e}")

    if errors:
        print("Warnings:", " | ".join(errors))

    # Ensure datetime
    df['ParsedDate'] = pd.to_datetime(df['ParsedDate'], errors='coerce')
    df['ParsedDate'] = df['ParsedDate'].dt.tz_localize(None).apply(lambda x: uk_tz.localize(x) if pd.notnull(x) else x)

    return df

# --- Status / ID / Display ---
def get_status(row):
    if "'" in row.Date_Time or "Half time" in row.Date_Time:
        return "Live", "🟢"
    elif row.HG != "-" and row.AG != "-":
        return "Finished", "🔵"
    else:
        return "Upcoming", "⚪"

# def build_match_id(row):
#     return f"{row.Home}-vs-{row.Away}_{row.Date_Time}_{row.Competition}"

# --- Build match_id using ParsedDate instead of Date_Time ---
def build_match_id(row):
    """
    Stable match identifier using Home-Away, ISO formatted ParsedDate, Competition
    """
    # dt_str = row.ParsedDate.isoformat() if pd.notna(row.ParsedDate) else "TBD"
    return f"{row.Home}-vs-{row.Away}" #_{dt_str}_{row.Competition}"

def trigger_toast(message: str, toast_type: str = "info"):
    st.markdown(
        f"""
        <script>
        showToast("{message}", "{toast_type}");
        </script>
        """,
        unsafe_allow_html=True
    )

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

