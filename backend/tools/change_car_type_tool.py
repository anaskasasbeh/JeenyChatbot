from langchain.tools import BaseTool
from typing import Optional, Any
import json
import os
from jeeny_agent.routing import compute_trip
from jeeny_agent.driver import generate_driver_location
from jeeny_agent.mapping import create_trip_map
from jeeny_agent.models import Location, TripInfo
from tools.car_type_selector_tool import CarTypeSelectorTool

class ChangeCarTypeTool(BaseTool):
    name: str = "change_car_type"
    description: str = (
        "تُستخدم هذه الأداة لتغيير نوع السيارة للرحلة الأخيرة أو عندما يطلب المستخدم تغيير/تعديل نوع السيارة. "
        "تعمل مع الرحلة المحفوظة في الذاكرة وتعيد حساب التكلفة والتفاصيل بناءً على نوع السيارة الجديد. "
        "مثال: 'غير نوع السيارة'، 'بدي سيارة VIP'، 'اعملها تاكسي بدل عادية'"
    )
    
    # إضافة model_config للسماح بـ arbitrary attributes في Pydantic v2
    model_config = {"arbitrary_types_allowed": True, "extra": "allow"}
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # الآن يمكن إضافة attributes مخصصة
        object.__setattr__(self, 'last_trip_data', None)
        
    def _extract_new_car_type(self, query: str) -> str:
        """استخراج نوع السيارة الجديد من طلب المستخدم"""
        car_type_tool = CarTypeSelectorTool()
        new_car_type = car_type_tool._run(query)
        print(f"[DEBUG] نوع السيارة الجديد المطلوب: {new_car_type}")
        return new_car_type
    
    def set_last_trip(self, start_loc: Location, end_loc: Location, original_car_type: str):
        """حفظ بيانات الرحلة الأخيرة"""
        object.__setattr__(self, 'last_trip_data', {
            "start_location": start_loc,
            "end_location": end_loc,
            "car_type": original_car_type  # تغيير من original_car_type إلى car_type
        })
        print(f"[DEBUG] تم حفظ بيانات الرحلة الأخيرة: {original_car_type}")
        
    def _run(self, query: str) -> str:
        try:
            # التحقق من وجود رحلة سابقة
            if not hasattr(self, 'last_trip_data') or not self.last_trip_data:
                return "❌ لا توجد رحلة سابقة لتغيير نوع السيارة. يرجى طلب رحلة جديدة أولاً."
            
            # استخراج نوع السيارة الجديد
            new_car_type = self._extract_new_car_type(query)
            
            # التحقق من صحة نوع السيارة
            valid_car_types = ["عادية", "تاكسي", "عائلية", "VIP"]
            if new_car_type not in valid_car_types:
                return f"❌ نوع السيارة '{new_car_type}' غير صحيح. الأنواع المتاحة: {', '.join(valid_car_types)}"
            
            # التحقق إذا كان نفس النوع الحالي
            if new_car_type == self.last_trip_data["car_type"]:
                return f"✅ نوع السيارة محدد مسبقاً كـ '{new_car_type}'. لا حاجة للتغيير."
            
            # الحصول على بيانات الرحلة السابقة
            start_loc = self.last_trip_data["start_location"]
            end_loc = self.last_trip_data["end_location"]
            old_car_type = self.last_trip_data["car_type"]
            
            print(f"[DEBUG] تغيير نوع السيارة من '{old_car_type}' إلى '{new_car_type}'")
            
            # إعادة حساب تفاصيل الرحلة بنوع السيارة الجديد
            trip = compute_trip(start_loc, end_loc, new_car_type)
            
            # إنشاء معلومات الرحلة الجديدة
            trip_info = TripInfo(
                distance=trip.distance,
                duration=trip.duration,
                cost=trip.cost,
                car_type=new_car_type
            )
            
            # توليد بيانات السائق الجديد
            driver = generate_driver_location(start_loc, new_car_type)
            
            # تحديث بيانات الرحلة المحفوظة بنوع السيارة الجديد
            object.__setattr__(self, 'last_trip_data', {
                "start_location": start_loc,
                "end_location": end_loc,
                "car_type": new_car_type  # هنا المشكلة: كان بيحفظ original_car_type
            })
            
            # تحديث البيانات المشتركة أيضاً
            from tools.get_directions_tool import set_shared_trip_data
            set_shared_trip_data(start_loc, end_loc, new_car_type)
            print(f"[DEBUG] تم تحديث البيانات المشتركة بنوع السيارة الجديد: {new_car_type}")
            
            # رسم الخريطة الجديدة
            map_info = ""
            try:
                map_filename = create_trip_map(
                    user_location={"lat": start_loc.lat, "lng": start_loc.lng},
                    driver_location={
                        "lat": driver['lat'], 
                        "lng": driver['lng'],
                        "distance_m": driver['distance_m'],
                        "arrival_time_min": driver['arrival_time_min'],
                        "car_type": new_car_type
                    },
                    destination_location={"lat": end_loc.lat, "lng": end_loc.lng},  
                    user_name="انس",
                    driver_name="ابو ثائر"
                )
                map_info = f"🗺️ تم إنشاء خريطة جديدة: {map_filename}"
            except Exception as e:
                print(f"DEBUG: خطأ في إنشاء الخريطة: {e}")
            
            # بناء الاستجابة
            response_lines = [
                f"✅ تم تغيير نوع السيارة من '{old_car_type}' إلى '{new_car_type}'",
                "",
                "🚗 التفاصيل المحدثة:",
                f"📍 من: {start_loc.name}",
                f"🎯 إلى: {end_loc.name}",
                f"🚖 السائق الجديد على بعد {driver['distance_m']} متر، سيصل خلال {driver['arrival_time_min']} دقيقة",
                f"⏱ الوقت المتوقع: {trip_info.duration}",
                f"📏 المسافة: {trip_info.distance}",
                f"💰 التكلفة الجديدة: {trip_info.cost} د.أ",
                f"🚘 نوع السيارة: {trip_info.car_type}"
            ]
            
            # إضافة ملاحظة السعر حسب نوع السيارة
            price_notes = {
                "عادية": "",
                "تاكسي": "📝 ملاحظة: (زيادة 15% للتاكسي)",
                "عائلية": "📝 ملاحظة: (زيادة 30% للسيارة العائلية)",
                "VIP": "📝 ملاحظة: (زيادة 50% للسيارة المميزة)"
            }
            
            if new_car_type in price_notes and price_notes[new_car_type]:
                response_lines.append(price_notes[new_car_type])
            
            # إضافة معلومات الخريطة
            if map_info:
                response_lines.append("")
                response_lines.append(map_info)
            
            return "\n".join(response_lines)
            
        except Exception as e:
            print(f"[خطأ في تغيير نوع السيارة] {str(e)}")
            return f"❌ عذراً، حدث خطأ أثناء تغيير نوع السيارة: {str(e)}"
    
    async def _arun(self, query: str) -> str:
        return self._run(query)