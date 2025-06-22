import os
from googlemaps import Client
from jeeny_agent.models import TripInfo, Location

gmaps = Client(key=os.getenv("GOOGLE_API_KEY"))

BASE_FARE = 0.5
RATE_PER_KM = 0.25
RATE_PER_MIN = 0.05

def compute_trip(start: Location, end: Location, car_type: str = "عادية") -> TripInfo:
    # إضافة debug لمعرفة نوع السيارة الواصل
    print(f"[DEBUG] compute_trip received car_type: '{car_type}'")
    
    directions = gmaps.directions((start.lat, start.lng), (end.lat, end.lng), mode="driving")
    leg = directions[0]['legs'][0]
    distance = leg['distance']['text']
    duration = leg['duration']['text']
    dist_km = leg['distance']['value'] / 1000
    dur_min = leg['duration']['value'] / 60
    
    # حساب السعر الأساسي
    base_cost = BASE_FARE + dist_km * RATE_PER_KM + dur_min * RATE_PER_MIN
    print(f"[DEBUG] Base cost: {base_cost}")
    
    # تحديد مضاعف السعر بناءً على نوع السيارة
    car_multipliers = {
        "عادية": 1.0,
        "تاكسي": 1.15,
        "عائلية": 1.3,
        "VIP": 1.5
    }
    
    # التأكد من نوع السيارة وطباعة تفاصيل التصحيح
    mult = car_multipliers.get(car_type, 1.0)
    print(f"[DEBUG] Car type: '{car_type}', Multiplier: {mult}")
    
    # إذا لم نجد النوع، استخدم القيمة الافتراضية مع تحذير
    if car_type not in car_multipliers:
        print(f"[WARNING] Unknown car type '{car_type}', using default multiplier 1.0")
        mult = 1.0
    
    # حساب التكلفة النهائية
    final_cost = round(base_cost * mult, 2)
    print(f"[DEBUG] Final cost: {base_cost} * {mult} = {final_cost}")
    
    return TripInfo(
        distance=distance, 
        duration=duration, 
        cost=final_cost, 
        car_type=car_type
    )