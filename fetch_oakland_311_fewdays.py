import requests
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv
import logging

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO)

# Print the DATABASE_URL for debugging
logging.info(f"DATABASE_URL: {os.getenv('DATABASE_URL')}")

# Constants
API_URL = "https://seeclickfix.com/api/v2/issues"
DAYS_BACK = 3  # Fetch complaints from the last 3 days
PER_PAGE = 100  # Max per page
MAX_PAGES = 30  # Limit pages to prevent long fetch times
PLACE_URL_NAME = "us-ca-oakland"  # SeeClickFix URL name for Oakland

# Generate a properly formatted 'after' timestamp
date_since = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).isoformat()

# Database connection
DATABASE_URL = os.getenv('DATABASE_URL')

try:
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    logging.info("Successfully connected to the database.")
except psycopg2.OperationalError as e:
    logging.error(f"Error connecting to the database: {e}")
    exit(1)

# Function to fetch recent complaints in Oakland with pagination
def fetch_recent_oakland_issues():
    issues = []
    page = 1

    while True:
        logging.info(f"Fetching page {page}...")
        params = {
            "place_url": PLACE_URL_NAME,
            "after": date_since,
            "per_page": PER_PAGE,
            "page": page
        }

        response = requests.get(API_URL, params=params)

        if response.status_code != 200:
            logging.error(f"Error fetching data: {response.text}")
            break

        data = response.json().get("issues", [])
        if not data:
            logging.info("No more complaints found.")
            break

        issues.extend(data)
        page += 1

        if page > MAX_PAGES:
            logging.info("Reached max pages, stopping pagination.")
            break

    return issues

# Fetch recent data
issues = fetch_recent_oakland_issues()

# Check for duplicates and insert new data
insert_query = """
INSERT INTO oakland_311_complaints (
    summary, description, status, created_at, updated_at, acknowledged_at, closed_at, reopened_at,
    lat, lng, address, request_type_id, request_type_title, request_type_organization,
    reporter_id, reporter_name, reporter_role, reporter_avatar, reporter_html_url,
    html_url, photo_url
) VALUES %s
ON CONFLICT (id) DO NOTHING
"""

# Prepare data for insertion
data_to_insert = [
    (
        issue.get('summary'), 
        issue.get('description'), 
        issue.get('status'), 
        issue.get('created_at'), 
        issue.get('updated_at'),
        issue.get('acknowledged_at'), 
        issue.get('closed_at'), 
        issue.get('reopened_at'), 
        issue.get('lat'), 
        issue.get('lng'),
        issue.get('address'), 
        issue.get('request_type', {}).get('id'), 
        issue.get('request_type', {}).get('title'), 
        issue.get('request_type', {}).get('organization'),
        issue.get('reporter', {}).get('id'), 
        issue.get('reporter', {}).get('name'), 
        issue.get('reporter', {}).get('role'), 
        issue.get('reporter', {}).get('avatar', {}).get('full'),
        issue.get('reporter', {}).get('html_url'), 
        issue.get('html_url'), 
        issue.get('photo_url')  # Use get method to handle missing keys
    ) for issue in issues
]

# Insert data into the database
execute_values(cursor, insert_query, data_to_insert)

conn.commit()
cursor.close()
conn.close()