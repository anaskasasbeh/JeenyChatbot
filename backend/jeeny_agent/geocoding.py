import os
import json
from functools import lru_cache
import googlemaps
from rapidfuzz import process
from jeeny_agent.models import Location
import re

API_KEY = os.getenv("GOOGLE_API_KEY")
gmaps = googlemaps.Client(key=API_KEY)

def resolve_address_to_coordinates(address: str) -> tuple:
    try:
        print(f"[DEBUG] محاولة تحويل العنوان: {address}")
        
        # إذا كان العنوان فارغ أو None
        if not address or not address.strip():
            print(f"[تحذير] العنوان فارغ")
            return None, None
        
        # التحقق أولاً إذا كان العنوان يحتوي على إحداثيات مباشرة
        if is_coordinate_format(address):
            print(f"[DEBUG] العنوان يحتوي على إحداثيات مباشرة")
            return parse_coordinates(address)
        
        # إضافة "الأردن" للبحث مباشرة
        search_query = f"{address}, الأردن"
        print(f"[DEBUG] البحث باستخدام: {search_query}")
        
        geocode_result = gmaps.geocode(search_query)
        
        # إذا لم نجد نتائج، جرب مع Jordan بالإنجليزية
        if not geocode_result:
            search_query = f"{address}, Jordan"
            print(f"[DEBUG] محاولة ثانية مع: {search_query}")
            geocode_result = gmaps.geocode(search_query)
        
        if not geocode_result:
            print(f"[تحذير] لم يتم العثور على إحداثيات للعنوان: {address}")
            return None, None
        
        # أخذ أول نتيجة والتحقق من الإحداثيات
        location = geocode_result[0]['geometry']['location']
        lat = location.get('lat', None)
        lng = location.get('lng', None)
        
        if lat is None or lng is None:
            print(f"[تحذير] الإحداثيات غير صالحة للعنوان: {address}")
            return None, None
        
        # التحقق من أن الإحداثيات ضمن حدود الأردن
        if not is_coordinates_in_jordan(lat, lng):
            print(f"[تحذير] الإحداثيات خارج حدود الأردن: {lat}, {lng}")
            return None, None
        
        print(f"[نجح] تم العثور على إحداثيات: {lat}, {lng}")
        return lat, lng
        
    except Exception as e:
        print(f"[خطأ] تعذر تحويل العنوان إلى إحداثيات: {e}")
        return None, None

def is_coordinates_in_jordan(lat: float, lng: float) -> bool:
    """التحقق من أن الإحداثيات ضمن حدود الأردن"""
    # حدود الأردن التقريبية
    # خط العرض: من 29.11 إلى 33.37
    # خط الطول: من 34.88 إلى 39.30
    
    if 29.0 <= lat <= 33.5 and 34.8 <= lng <= 39.5:
        print(f"[DEBUG] الإحداثيات ضمن حدود الأردن: {lat}, {lng}")
        return True
    else:
        print(f"[DEBUG] الإحداثيات خارج حدود الأردن: {lat}, {lng}")
        return False

def is_coordinate_format(address: str) -> bool:
    """التحقق إذا كان النص يحتوي على إحداثيات بصيغة lat,lng"""
    if not address:
        return False
    # البحث عن نمط: رقم.رقم، رقم.رقم
    pattern = r'^\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*$'
    return bool(re.match(pattern, address.strip()))

def parse_coordinates(coord_str: str) -> tuple:
    """تحويل النص الذي يحتوي على إحداثيات إلى lat, lng"""
    try:
        parts = coord_str.strip().split(',')
        if len(parts) == 2:
            lat = float(parts[0].strip())
            lng = float(parts[1].strip())
            return lat, lng
    except ValueError:
        pass
    return None, None