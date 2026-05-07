import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- Configuration ---
BASE_DIR = Path(__file__).resolve().parent

SEEN_FILE = BASE_DIR / "seen_jobs.json"
USERS_FILE = BASE_DIR / "users.json"

LAST_UPDATE_ID = 0

# Load environment variables from .env
load_dotenv()

JSEARCH_API_KEY = os.getenv("JSEARCH_API_KEY")

# --- Job Query ---
JOB_QUERY = os.getenv(
    "JOB_QUERY",
    "Java developer fresher in Bengaluru, India",
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

CHECK_INTERVAL = 21600  # 15 hours

# --- Requests Session with Retry Handling ---
session = requests.Session()

retries = Retry(
    total=3,
    backoff_factor=2,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"]
)

adapter = HTTPAdapter(max_retries=retries)

session.mount("https://", adapter)
session.mount("http://", adapter)


# =========================================================
# Seen Jobs Storage
# =========================================================

def load_seen_jobs():
    """Loads previously seen job IDs from local JSON file."""

    if not SEEN_FILE.exists():
        return set()

    with open(SEEN_FILE, "r", encoding="utf-8") as f:

        try:
            data = json.load(f)

        except json.JSONDecodeError:
            data = []

    return set(data)


def save_seen_jobs(seen_ids):
    """Saves seen job IDs to prevent duplicate alerts."""

    with open(SEEN_FILE, "w", encoding="utf-8") as f:

        json.dump(
            list(seen_ids),
            f,
            ensure_ascii=False,
            indent=2
        )


# =========================================================
# Telegram Users Storage
# =========================================================

def load_users():

    if not USERS_FILE.exists():

        with open(USERS_FILE, "w") as f:
            json.dump([], f)

        return []

    try:

        with open(USERS_FILE, "r", encoding="utf-8") as f:

            data = json.load(f)

            if isinstance(data, list):
                return data

    except Exception:
        pass

    return []


def save_users(users):

    with open(USERS_FILE, "w", encoding="utf-8") as f:

        json.dump(
            users,
            f,
            ensure_ascii=False,
            indent=2
        )


def add_user(chat_id):

    users = load_users()

    if chat_id not in users:

        users.append(chat_id)

        save_users(users)

        print(f"New user added: {chat_id}")


# =========================================================
# Detect Telegram Users
# =========================================================

def fetch_new_users():

    global LAST_UPDATE_ID

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/getUpdates"
    )

    try:

        response = session.get(url, timeout=15)

        response.raise_for_status()

        data = response.json()

        results = data.get("result", [])

        for item in results:

            update_id = item.get("update_id", 0)

            if update_id <= LAST_UPDATE_ID:
                continue

            LAST_UPDATE_ID = update_id

            message = item.get("message", {})

            chat = message.get("chat", {})

            chat_id = chat.get("id")

            if chat_id:
                add_user(chat_id)

    except Exception as e:

        print(f"Failed fetching users: {e}")


# =========================================================
# Fetch Jobs
# =========================================================

def fetch_latest_jobs():
    """
    Fetches jobs from JSearch API and applies Bengaluru filtering.
    """

    if not JSEARCH_API_KEY:
        print("Error: JSEARCH_API_KEY is missing in .env")
        return []

    url = "https://jsearch.p.rapidapi.com/search"

    headers = {
        "X-RapidAPI-Key": JSEARCH_API_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
    }

    querystring = {
        "query": JOB_QUERY,
        "page": "1",
        "num_pages": "1",
        "date_posted": "all"
    }

    print(f"\nFetching jobs for: '{JOB_QUERY}'")

    try:

        response = session.get(
            url,
            headers=headers,
            params=querystring,
            timeout=15
        )

        response.raise_for_status()

        data = response.json()

    except Exception as e:

        print(f"Failed to fetch jobs: {e}")
        return []

    raw_jobs = data.get("data", [])

    print(f"JSearch returned {len(raw_jobs)} jobs.")

    jobs = []

    target_locations = ["bengaluru", "bangalore"]

    for item in raw_jobs:

        job_id = item.get("job_id")

        if not job_id:
            continue

        city = (item.get("job_city") or "").lower()
        state = (item.get("job_state") or "").lower()
        country = (item.get("job_country") or "").lower()

        location_raw = " ".join([
            city,
            state,
            country
        ]).lower()

        if not any(
            loc in location_raw
            for loc in target_locations
        ):
            continue

        title = item.get("job_title", "N/A")

        company = item.get(
            "employer_name",
            "N/A"
        )

        display_city = (
            item.get("job_city")
            or "Bengaluru"
        )

        display_country = (
            item.get("job_country")
            or "India"
        )

        location_str = (
            f"{display_city}, "
            f"{display_country}"
        )

        url_link = (
            item.get("job_apply_link")
            or item.get("job_google_link")
            or "No link available"
        )

        posted_at = item.get(
            "job_posted_at_datetime_utc"
        )

        if posted_at and isinstance(posted_at, str):

            try:
                posted_at = posted_at.split("T")[0]

            except Exception:
                posted_at = "N/A"

        else:
            posted_at = "N/A"

        jobs.append({
            "id": job_id,
            "title": title,
            "company": company,
            "location": location_str,
            "url": url_link,
            "posted_at": posted_at,
        })

    print(f"{len(jobs)} jobs passed Bengaluru filter.")

    return jobs


# =========================================================
# Telegram Broadcast
# =========================================================

def send_telegram_message(text: str):
    """Sends message to ALL Telegram users."""

    users = load_users()

    if not users:
        print("No Telegram users registered.")
        return

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    for chat_id in users:

        payload = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
            "parse_mode": "HTML"
        }

        try:

            response = session.post(
                url,
                json=payload,
                timeout=10
            )

            response.raise_for_status()

            print(f"Alert sent to {chat_id}")

        except Exception as e:

            print(
                f"Failed sending to "
                f"{chat_id}: {e}"
            )


# =========================================================
# Message Formatting
# =========================================================

def format_job_message(job):
    """Formats Telegram message using HTML."""

    return (
        f"🚨 <b>New Job Alert: Bengaluru</b>\n\n"
        f"💼 <b>Role:</b> {job['title']}\n"
        f"🏢 <b>Company:</b> {job['company']}\n"
        f"📍 <b>Location:</b> {job['location']}\n"
        f"📅 <b>Posted:</b> {job['posted_at']}\n\n"
        f"🔗 {job['url']}"
    )


# =========================================================
# Main Job Check
# =========================================================

def check_and_notify():
    """Checks for new jobs and sends Telegram alerts."""

    seen_ids = load_seen_jobs()

    jobs = fetch_latest_jobs()

    if not jobs:
        print("No matching jobs found.")
        return

    new_jobs = [
        job for job in jobs
        if job["id"] not in seen_ids
    ]

    print(
        f"Found {len(jobs)} jobs, "
        f"{len(new_jobs)} are new."
    )

    for job in new_jobs:

        msg = format_job_message(job)

        send_telegram_message(msg)

        seen_ids.add(job["id"])

        time.sleep(1)

    if new_jobs:

        save_seen_jobs(seen_ids)

        print("Seen jobs database updated.")


# =========================================================
# Runner
# =========================================================

if __name__ == "__main__":

    print("Starting Job Bot...")
    print("Users must press START in Telegram.")
    print("Press Ctrl+C to stop.\n")

    try:

        while True:

            # Detect new Telegram users
            fetch_new_users()

            # Check jobs
            check_and_notify()

            print(
                f"\nSleeping for "
                f"{CHECK_INTERVAL // 60} minutes...\n"
            )

            time.sleep(CHECK_INTERVAL)

    except KeyboardInterrupt:

        print("\nBot stopped manually.")