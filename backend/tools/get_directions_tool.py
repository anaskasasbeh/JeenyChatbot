from langchain.tools import BaseTool
from typing import Optional
import requests
import os
import json
from jeeny_agent.nlu import extract_locations
from jeeny_agent.nlu import check_saved_locations
from jeeny_agent.nlu import get_location_name_from_coordinates
from jeeny_agent.nlu import is_latlng
from jeeny_agent.nlu import parse_latlng
from jeeny_agent.geocoding import resolve_address_to_coordinates
from jeeny_agent.routing import compute_trip
from jeeny_agent.driver import generate_driver_location
from jeeny_agent.mapping import create_trip_map
from jeeny_agent.models import Location
from jeeny_agent.models import TripInfo
from tools.car_type_selector_tool import CarTypeSelectorTool

# متغير global لمشاركة بيانات الرحلة بين الأدوات
_shared_trip_data = None

def get_shared_trip_data():
    """الحصول على بيانات الرحلة المشتركة"""
    return _shared_trip_data

def set_shared_trip_data(start_loc, end_loc, car_type):
    """حفظ بيانات الرحلة المشتركة"""
    global _shared_trip_data
    _shared_trip_data = {
        "start_location": start_loc,
        "end_location": end_loc,
        "car_type": car_type
    }

class GetDirectionsTool(BaseTool):
    name: str = "get_directions_arabic"
    description: str = (
        "غالبا يجب ان يتم استخدام هذه الاداة في اول مراحل تشغيل البرنامج ،تقوم هذه الأداة بحساب اتجاهات القيادة بين نقطتين في الأردن بناءً على وصف المستخدم باللغة العامية. مثل تطبيق Uber"
        "تأخذ النص، تستخرج الموقع الحالي والوجهة، وتحسب المسافة والوقت والتكلفة التقديرية، وتعرض النتيجة بالعربية."
    )

    def _run(self, query: str) -> str:
        try:
            # استدعاء أداة اختيار نوع السيارة أولاً
            car_type_tool = CarTypeSelectorTool()
            car_type = car_type_tool._run(query)
            print(f"[DEBUG] Selected car_type: '{car_type}'")
            
            # التحقق من صحة نوع السيارة
            valid_car_types = ["عادية", "تاكسي", "عائلية", "VIP"]
            if car_type not in valid_car_types:
                print(f"[WARNING] Invalid car type '{car_type}', defaulting to 'عادية'")
                car_type = "عادية"
            
            locations = check_saved_locations(query)
            if "error" in locations:
                return f"❌ خطأ في معالجة المواقع: {locations['error']}"

            # تخزين القيم المؤقتة
            start_name_temp = locations["start_location"]
            end_name_temp = locations["end_location"]
            country = locations["country"]

            if not start_name_temp or not end_name_temp:
                return "❌ لم يتم تحديد نقطة البداية أو الوجهة بشكل صحيح. يرجى إعادة المحاولة بوضوح أكثر."

            print(f"[DEBUG] معالجة البداية: {start_name_temp}")
            print(f"[DEBUG] معالجة النهاية: {end_name_temp}")

            # معالجة نقطة البداية
            if is_latlng(start_name_temp):
                print(f"[DEBUG] البداية عبارة عن إحداثيات: {start_name_temp}")
                start_lat_temp, start_lng_temp = parse_latlng(start_name_temp)
                # استخدام اسم عام للعرض
                start_display_name = get_location_name_from_coordinates(start_name_temp)
                if start_display_name == start_name_temp:  # إذا لم نجد اسم مطابق
                    start_display_name = "الموقع المحدد"
            else:
                print(f"[DEBUG] البداية عبارة عن عنوان: {start_name_temp}")
                start_lat_temp, start_lng_temp = resolve_address_to_coordinates(start_name_temp)
                start_display_name = start_name_temp
                
            # التحقق من صحة إحداثيات البداية
            if start_lat_temp is None or start_lng_temp is None:
                return f"❌ عذراً، لم أتمكن من العثور على موقع البداية: '{start_name_temp}'. يرجى التأكد من صحة اسم المكان."

            # معالجة نقطة النهاية
            if is_latlng(end_name_temp):
                print(f"[DEBUG] النهاية عبارة عن إحداثيات: {end_name_temp}")
                end_lat_temp, end_lng_temp = parse_latlng(end_name_temp)
                # استخدام اسم عام للعرض
                end_display_name = get_location_name_from_coordinates(end_name_temp)
                if end_display_name == end_name_temp:  # إذا لم نجد اسم مطابق
                    end_display_name = "الوجهة المحددة"
            else:
                print(f"[DEBUG] النهاية عبارة عن عنوان: {end_name_temp}")
                end_lat_temp, end_lng_temp = resolve_address_to_coordinates(end_name_temp)
                end_display_name = end_name_temp
                
            # التحقق من صحة إحداثيات النهاية
            if end_lat_temp is None or end_lng_temp is None:
                return f"❌ عذراً، لم أتمكن من العثور على موقع الوجهة: '{end_name_temp}'. يرجى التأكد من صحة اسم المكان."
        
            # إنشاء كائنات Location بعد التأكد من القيم
            start_loc = Location(name=start_display_name, lat=start_lat_temp, lng=start_lng_temp)
            end_loc = Location(name=end_display_name, lat=end_lat_temp, lng=end_lng_temp)

            print(f"[DEBUG] start_loc = {start_loc}")
            print(f"[DEBUG] end_loc = {end_loc}")
            print(f"[DEBUG] Passing car_type to compute_trip: '{car_type}'")

            # حفظ بيانات الرحلة للمشاركة مع أدوات أخرى
            set_shared_trip_data(start_loc, end_loc, car_type)
            print(f"[DEBUG] تم حفظ بيانات الرحلة المشتركة")

            # حساب تفاصيل الرحلة مع نوع السيارة المحدد
            trip = compute_trip(start_loc, end_loc, car_type)

            print(f"[DEBUG] trip object = {trip}")
            print(f"[DEBUG] trip.cost = {trip.cost}")
            print(f"[DEBUG] trip.car_type = {trip.car_type}")

            # إنشاء كائن TripInfo وتعيين القيم من trip
            trip_info = TripInfo(
                distance=trip.distance,
                duration=trip.duration,
                cost=trip.cost,
                car_type=car_type
            )
            print(f"[DEBUG] trip_info = {trip_info}")
            
            # توليد بيانات السائق مع نوع السيارة
            driver = generate_driver_location(start_loc, car_type)
            print(f"[DEBUG] driver = {driver}")
            
            # رسم الخريطة
            map_info = ""
            try:
                map_filename = create_trip_map(
                    user_location={"lat": start_loc.lat, "lng": start_loc.lng},
                    driver_location={
                        "lat": driver['lat'], 
                        "lng": driver['lng'],
                        "distance_m": driver['distance_m'],
                        "arrival_time_min": driver['arrival_time_min'],
                        "car_type": car_type
                    },
                    destination_location={"lat": end_loc.lat, "lng": end_loc.lng},  
                    user_name="انس",
                    driver_name="ابو ثائر"
                )
                print(f"DEBUG: تم إنشاء خريطة: {map_filename}")
                map_info = f"🗺️ تم إنشاء خريطة الرحلة: {map_filename}"
            except Exception as e:
                print(f"DEBUG: خطأ في إنشاء الخريطة: {e}")

            # بناء الاستجابة المنسقة مع الإيقونات والتنسيق الصحيح
            response_lines = [
                "🚗 تفاصيل الرحلة:",
                f"📍 من: {start_loc.name}",
                f"🎯 إلى: {end_loc.name}",
                f"🚖 السائق على بعد {driver['distance_m']} متر، سيصل خلال {driver['arrival_time_min']} دقيقة",
                f"⏱ الوقت المتوقع: {trip_info.duration}",
                f"📏 المسافة: {trip_info.distance}",
                f"💰 التكلفة المقدرة: {trip_info.cost} د.أ",
                f"🚘 نوع السيارة: {trip_info.car_type}"
            ]
            
            # إضافة ملاحظة السعر حسب نوع السيارة
            price_notes = {
                "عادية": "",
                "تاكسي": "📝 ملاحظة: (زيادة 15% للتاكسي)",
                "عائلية": "📝 ملاحظة: (زيادة 30% للسيارة العائلية)",
                "VIP": "📝 ملاحظة: (زيادة 50% للسيارة المميزة)"
            }
            
            if car_type in price_notes and price_notes[car_type]:
                response_lines.append(price_notes[car_type])
            
            # إضافة معلومات الخريطة إذا توفرت
            if map_info:
                response_lines.append("")  # سطر فارغ للفصل
                response_lines.append(map_info)
            
            # دمج جميع الأسطر مع فواصل الأسطر
            final_response = "\n".join(response_lines)
            
            return final_response
            
        except Exception as e:
            print(f"[خطأ كامل] {str(e)}")
            return f"❌ عذراً، حدث خطأ في معالجة طلبك. يرجى التأكد من صحة أسماء المواقع والمحاولة مرة أخرى.\n\n🔍 تفاصيل الخطأ: {str(e)}"

    async def _arun(self, query: str) -> str:
        return self._run(query)