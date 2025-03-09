import pandas as pd
import folium
from flask import Flask, request, render_template
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import os
from datetime import timedelta
from folium.plugins import HeatMap

app = Flask(__name__)

# Updated CSV filename
CSV_FILENAME = "oakland_311_complaints_365_days.csv"

# Check if the file exists
if not os.path.exists(CSV_FILENAME):
    print(f"Error: File {CSV_FILENAME} not found. Please ensure the dataset exists.")
    df = pd.DataFrame()  # Empty DataFrame
else:
    df = pd.read_csv(CSV_FILENAME)

    # Convert `created_at` to proper datetime format and ensure it is in UTC
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True)

# Required columns
REQUIRED_COLUMNS = {
    "id", "summary", "description", "status", "created_at", "updated_at",
    "acknowledged_at", "closed_at", "reopened_at", "lat", "lng", "address",
    "request_type.id", "request_type.title", "request_type.organization",
    "reporter.id", "reporter.name", "reporter.role", "reporter.avatar",
    "reporter.html_url", "html_url", "photo_url"
}

# Ensure DataFrame has the correct columns
if not df.empty and not REQUIRED_COLUMNS.issubset(df.columns):
    print("Error: CSV file is missing required columns.")
    df = pd.DataFrame()  # Reset to empty
else:
    # Extract unique categories from the dataset
    df["request_type.title"].fillna("Unknown", inplace=True)  # Ensure no missing values
    categories = sorted(df["request_type.title"].unique())  # Get sorted list of unique categories

# Function to get latitude & longitude from an address
def get_lat_lon(address):
    geolocator = Nominatim(user_agent="311data_search")
    location = geolocator.geocode(address)
    if location:
        return location.latitude, location.longitude
    return None, None

@app.route("/", methods=["GET", "POST"])
def index():
    complaints = []
    map_html = None
    selected_categories = []
    address = ""
    radius = 0.5
    start_date = ""
    end_date = ""
    total_issues = 0
    issues_by_category = {}
    issues_by_time = {}

    if df.empty:
        return render_template("index.html", error="No data available. Ensure the CSV file is present.", complaints=[], map_html=None, categories=[], selected_categories=[])

    if request.method == "POST":
        address = request.form.get("address")
        radius = float(request.form.get("radius", 0.5))
        start_date = request.form.get("start_date")
        end_date = request.form.get("end_date")
        selected_categories = request.form.getlist("categories")  # Get multiple selected categories

        lat, lon = get_lat_lon(address)
        if not lat or not lon:
            return render_template("index.html", error="Invalid address. Try again.", complaints=[], map_html=None, categories=categories, selected_categories=selected_categories)

        # Convert dates from string to timezone-aware datetime
        try:
            start_date = pd.to_datetime(start_date, errors="coerce", utc=True) if start_date else None
            end_date = pd.to_datetime(end_date, errors="coerce", utc=True) if end_date else None
        except Exception:
            return render_template("index.html", error="Invalid date format. Use YYYY-MM-DD.", complaints=[], map_html=None, categories=categories, selected_categories=selected_categories)

        # Filter by date range
        filtered_df = df.copy()
        if start_date:
            filtered_df = filtered_df[filtered_df["created_at"] >= start_date]
        if end_date:
            filtered_df = filtered_df[filtered_df["created_at"] <= end_date]

        # Filter by multiple categories if selected
        if selected_categories:
            filtered_df = filtered_df[filtered_df["request_type.title"].isin(selected_categories)]

        # Calculate distances and filter data
        filtered_df["distance_miles"] = filtered_df.apply(lambda row: geodesic((lat, lon), (row["lat"], row["lng"])).miles, axis=1)
        filtered_df = filtered_df[filtered_df["distance_miles"] <= radius]

        if filtered_df.empty:
            return render_template("index.html", error="No complaints found within the specified criteria.", complaints=[], map_html=None, categories=categories, selected_categories=selected_categories)

        # Add index numbers to complaints
        filtered_df["index"] = range(1, len(filtered_df) + 1)
        complaints = filtered_df.to_dict(orient="records")

        # Generate summary statistics
        total_issues = len(filtered_df)
        issues_by_category = filtered_df["request_type.title"].value_counts().to_dict()

        # Determine the date range
        date_min = filtered_df["created_at"].min().date() if not filtered_df.empty else None
        date_max = filtered_df["created_at"].max().date() if not filtered_df.empty else None
        date_range = (date_max - date_min).days if date_min and date_max else 0

        # Choose appropriate time grouping
        if date_range <= 7:
            filtered_df["time_group"] = filtered_df["created_at"].dt.strftime('%Y-%m-%d')  # Daily
        elif date_range <= 90:
            filtered_df["time_group"] = filtered_df["created_at"].dt.to_period("W").astype(str)  # Weekly
        else:
            filtered_df["time_group"] = filtered_df["created_at"].dt.to_period("M").astype(str)  # Monthly

        # Aggregate issues by time period
        issues_by_time = filtered_df["time_group"].value_counts().sort_index().to_dict()
        issues_by_time = [{"date": period, "count": count} for period, count in issues_by_time.items()]

        # Generate interactive map for the default view
        map_center = [lat, lon]
        folium_map = folium.Map(location=map_center, zoom_start=14)

        # Add a yellow marker for the searched location
        folium.Marker(
            location=[lat, lon],
            popup=f"Search Location: {address}",
            tooltip="Search Address",
            icon=folium.Icon(color="yellow", icon="star")
        ).add_to(folium_map)

        # Add numbered complaint markers
        for index, row in filtered_df.iterrows():
            folium.Marker(
                location=[row["lat"], row["lng"]],
                popup=f"<b>#{row['index']}</b>: {row['summary']} ({row['status']}) - {round(row['distance_miles'], 2)} mi",
                tooltip=f"#{row['index']} {row['summary']}",
                icon=folium.DivIcon(
                    icon_size=(20, 20),
                    icon_anchor=(10, 10),
                    html=f'<div style="background-color:blue; color:white; font-weight:bold; text-align:center; border-radius:50%; width:24px; height:24px; line-height:24px;">{row["index"]}</div>'
                )
            ).add_to(folium_map)

        map_html = folium_map._repr_html_()

    return render_template("index.html", 
                           complaints=complaints, 
                           map_html=map_html, 
                           search_address=address if address else "", 
                           search_radius=radius, 
                           search_start_date=start_date.strftime('%Y-%m-%d') if start_date else "", 
                           search_end_date=end_date.strftime('%Y-%m-%d') if end_date else "",
                           categories=categories,
                           selected_categories=selected_categories,
                           total_issues=total_issues,
                           issues_by_category=issues_by_category,
                           issues_by_time=issues_by_time)

@app.route('/toggle_heatmap', methods=['POST'])
def toggle_heatmap():
    data = request.get_json()
    is_heatmap = data.get('heatmap', False)

    # Use the same filtering logic as in the index route
    address = data.get('address', '')
    radius = float(data.get('radius', 0.5))
    start_date = pd.to_datetime(data.get('start_date'), errors='coerce', utc=True) if data.get('start_date') else None
    end_date = pd.to_datetime(data.get('end_date'), errors='coerce', utc=True) if data.get('end_date') else None
    selected_categories = data.get('categories', [])

    lat, lon = get_lat_lon(address)
    if not lat or not lon:
        return {'success': False, 'message': 'Invalid address.'}

    # Filter the dataset
    filtered_df = df.copy()
    if start_date:
        filtered_df = filtered_df[filtered_df['created_at'] >= start_date]
    if end_date:
        filtered_df = filtered_df[filtered_df['created_at'] <= end_date]
    if selected_categories:
        filtered_df = filtered_df[filtered_df['request_type.title'].isin(selected_categories)]
    filtered_df['distance_miles'] = filtered_df.apply(lambda row: geodesic((lat, lon), (row['lat'], row['lng'])).miles, axis=1)
    filtered_df = filtered_df[filtered_df['distance_miles'] <= radius]

    # Create the map
    folium_map = folium.Map(location=[lat, lon], zoom_start=13)

    if is_heatmap:
        # Add heatmap layer with dynamic radius
        heat_data = [[row['lat'], row['lng']] for index, row in filtered_df.iterrows()]
        HeatMap(heat_data, radius=15, blur=10, max_zoom=15).add_to(folium_map)
    else:
        # Add markers
        for index, row in filtered_df.iterrows():
            folium.Marker([row['lat'], row['lng']], popup=row['summary']).add_to(folium_map)

    map_html = folium_map._repr_html_()
    return {'success': True, 'map_html': map_html}

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5005)