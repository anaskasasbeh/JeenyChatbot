from pydantic import BaseModel
from typing import Optional

class Location(BaseModel):
    name: str 
    lat: float 
    lng: float 

class TripInfo(BaseModel):
    distance: str
    duration: str
    cost: float
    car_type: str = "عادية"

