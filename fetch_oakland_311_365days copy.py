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
DAYS_BACK = 365  # Fetch complaints from the last 365 days
PER_PAGE = 100  # Max per page
MAX_PAGES = 350  # Safety limit to prevent endless loops
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

# Function to fetch all complaints in Oakland with pagination
def fetch_all_oakland_issues():
    issues = []
    page = 1

    while True:
        print(f"Fetching page {page}...")
        params = {
            "place_url": PLACE_URL_NAME,  # Restrict results to Oakland
            "after": date_since,
            "per_page": PER_PAGE,
            "page": page
        }

        response = requests.get(API_URL, params=params)

        if response.status_code != 200:
            print(f"Error fetching data: {response.text}")
            break

        data = response.json().get("issues", [])
        if not data:
            print("No more complaints found.")
            break

        # Add missing fields to avoid key errors
        for issue in data:
            issue["photo_url"] = issue.get("media", {}).get("representative_image_url", None)
            issue["html_url"] = issue.get("html_url", None)
            issue["address"] = issue.get("address", None)
            
            issue["request_type.id"] = issue.get("request_type", {}).get("id", None)
            issue["request_type.title"] = issue.get("request_type", {}).get("title", None)
            issue["request_type.organization"] = issue.get("request_type", {}).get("organization", None)

            issue["reporter.id"] = issue.get("reporter", {}).get("id", None)
            issue["reporter.name"] = issue.get("reporter", {}).get("name", None)
            issue["reporter.role"] = issue.get("reporter", {}).get("role", None)
            issue["reporter.avatar"] = issue.get("reporter", {}).get("avatar", {}).get("full", None)
            issue["reporter.html_url"] = issue.get("reporter", {}).get("html_url", None)

        issues.extend(data)
        page += 1

        if page > MAX_PAGES:
            print("Reached max pages, stopping pagination.")
            break

    return issues

# Fetch data
issues = fetch_all_oakland_issues()

# Insert data into the database
insert_query = """
INSERT INTO oakland_311_complaints (
    summary, description, status, created_at, updated_at, acknowledged_at, closed_at, reopened_at,
    lat, lng, address, request_type_id, request_type_title, request_type_organization,
    reporter_id, reporter_name, reporter_role, reporter_avatar, reporter_html_url,
    html_url, photo_url
) VALUES %s
"""
execute_values(cursor, insert_query, [
    (
        issue['summary'], issue['description'], issue['status'], issue['created_at'], issue['updated_at'],
        issue['acknowledged_at'], issue['closed_at'], issue['reopened_at'], issue['lat'], issue['lng'],
        issue['address'], issue['request_type.id'], issue['request_type.title'], issue['request_type.organization'],
        issue['reporter.id'], issue['reporter.name'], issue['reporter.role'], issue['reporter.avatar'],
        issue['reporter.html_url'], issue['html_url'], issue['photo_url']
    ) for issue in issues
])

conn.commit()
cursor.close()
conn.close()