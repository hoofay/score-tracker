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
ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?(?:Z|[+-]\d{2}:?\d{2})?")
EPOCH_RE = re.compile(r"\b\d{10,13}\b")

def _parse_epoch_or_iso_string(val: str):
    """Try ISO first, then epoch (10 or 13 digits). Return tz-aware Europe/London datetime or None."""
    if not val:
        return None
    val = val.strip()
    # try ISO
    m_iso = ISO_RE.search(val)
    if m_iso:
        try:
            dt = dtparser.isoparse(m_iso.group(0))
            # if no tzinfo, assume UTC (common) then convert to London
            if dt.tzinfo is None:
                dt = pytz.UTC.localize(dt).astimezone(uk_tz)
            else:
                dt = dt.astimezone(uk_tz)
            return dt
        except Exception:
            pass

    # try epoch-like numbers
    m_epoch = EPOCH_RE.search(val)
    if m_epoch:
        try:
            ep = int(m_epoch.group(0))
            # 13 digits => milliseconds
            if len(m_epoch.group(0)) == 13:
                ep = ep / 1000.0
            dt = datetime.fromtimestamp(ep, tz=pytz.UTC).astimezone(uk_tz)
            return dt
        except Exception:
            pass

    # last resort: try dateutil parse with dayfirst
    try:
        dt = dtparser.parse(val, dayfirst=True, fuzzy=True)
        if dt.tzinfo is None:
            dt = uk_tz.localize(dt)
        else:
            dt = dt.astimezone(uk_tz)
        return dt
    except Exception:
        return None

def extract_timestamp_from_element(el):
    """
    Look through common attributes and inner text for a real timestamp.
    Returns a tz-aware datetime in Europe/London or None.
    """
    if el is None:
        return None

    # 1) common attribute names
    candidate_attrs = [
        "datetime", "data-utc", "data-timestamp", "data-date", "data-time",
        "data-start", "data-unixtime", "data-unix", "data-unixtimestamp",
        "data-epoch", "data-timestring", "data-datetime", "data-start-date"
    ]
    for a in candidate_attrs:
        if el.has_attr(a):
            dt = _parse_epoch_or_iso_string(el[a])
            if dt:
                return dt

    # 2) <time datetime="...">
    time_tag = el.find("time")
    if time_tag and time_tag.has_attr("datetime"):
        dt = _parse_epoch_or_iso_string(time_tag["datetime"])
        if dt:
            return dt

    # 3) inline scripts or data-* on child elements
    for child in el.find_all(True, recursive=True):
        for a in child.attrs:
            # attr value may be list; coerce to string
            val = child.attrs.get(a)
            if isinstance(val, list):
                val = " ".join(val)
            if val and isinstance(val, str):
                dt = _parse_epoch_or_iso_string(val)
                if dt:
                    return dt

    # 4) last attempt: scan visible text for ISO/epoch
    raw = el.get_text(" ", strip=True)
    return _parse_epoch_or_iso_string(raw)


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
            # find the same elements (but keep elements, not just text)
            date_elements = page.find_all("div", class_="SimpleMatchCard_simpleMatchCard__matchContent__prwTf")
            date_texts = []
            date_parsed = []
            
            for el in date_elements:
                raw = el.get_text(" ", strip=True)
                parsed = extract_timestamp_from_element(el)
                date_texts.append(raw)
                date_parsed.append(parsed)
            
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
            # parsed = [parse_date(dt) for dt in dateTime]

            # Append to DataFrame
            df = pd.concat([df, pd.DataFrame({
                "Competition": league,
                "Home": home,
                "Away": away,
                "HG": home_scores,
                "AG": away_scores,
                "Date_Time": dateTime,
                "ParsedDate": date_parsed
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









