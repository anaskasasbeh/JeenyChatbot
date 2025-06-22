import os
import random
import requests
from geopy.point import Point
from geopy.distance import distance as geopy_distance
from jeeny_agent.models import Location

def snap_to_road(lat, lng, api_key):
    try:
        url = f"https://roads.googleapis.com/v1/snapToRoads?path={lat},{lng}&key={api_key}"
        response = requests.get(url)
        if response.status_code == 200:
            snapped_points = response.json().get("snappedPoints")
            if snapped_points:
                location = snapped_points[0]["location"]
                return location["latitude"], location["longitude"]
    except Exception as e:
        print(f"[تحذير] تعذر استخدام Google Roads API: {e}")
    return lat, lng

def generate_driver_location(user_loc: Location, car_type: str = "عادية") -> dict:
    d_m = random.randint(100,300)
    bearing = random.uniform(0,360)
    dest = geopy_distance(meters=d_m).destination(Point(user_loc.lat, user_loc.lng), bearing)
    lat, lng = snap_to_road(dest.latitude, dest.longitude, os.getenv("GOOGLE_API_KEY"))
    eta = round(d_m/200, 1)
    return {"lat":lat, "lng":lng, "car_type":car_type, "distance_m":d_m, "arrival_time_min":eta}
