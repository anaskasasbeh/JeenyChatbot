from langchain.tools import BaseTool
from langchain_openai import ChatOpenAI
from typing import Optional
import json
import os
from jeeny_agent.routing import compute_trip
from jeeny_agent.driver import generate_driver_location
from jeeny_agent.mapping import create_trip_map
from jeeny_agent.models import Location, TripInfo
from jeeny_agent.nlu import check_saved_locations
from jeeny_agent.geocoding import resolve_address_to_coordinates
from jeeny_agent.nlu import is_latlng, parse_latlng, get_location_name_from_coordinates
from dotenv import load_dotenv
import re

class ModifyLocationTool(BaseTool):
    name: str = "modify_location"
    description: str = (
        "تُستخدم هذه الأداة لتعديل نقطة البداية أو الوجهة للرحلة الحالية المحفوظة. "
        "يمكن للمستخدم تغيير إما نقطة البداية أو الوجهة أو كليهما معاً. "
        "مثال: 'غير الوجهة للسلط'، 'بدي أغير البداية'، 'خلاص صير من الزرقاء'، 'غير المكان لعجلون'"
    )
    
    # إضافة model_config للسماح بـ arbitrary attributes في Pydantic v2
    model_config = {"arbitrary_types_allowed": True, "extra": "allow"}
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        load_dotenv()
        # استخدام object.__setattr__ لتجنب مشكلة Pydantic
        object.__setattr__(self, '_llm', None)
        object.__setattr__(self, 'last_trip_data', None)
        
    @property
    def llm(self):
        """Lazy loading للـ LLM"""
        if self._llm is None:
            object.__setattr__(self, '_llm', ChatOpenAI(
                model="gpt-4o-mini",
                temperature=0, 
                openai_api_key=os.getenv("OPENAI_API_KEY")
            ))
        return self._llm

    def set_last_trip(self, start_loc: Location, end_loc: Location, car_type: str):
        """حفظ بيانات الرحلة الأخيرة"""
        object.__setattr__(self, 'last_trip_data', {
            "start_location": start_loc,
            "end_location": end_loc,
            "car_type": car_type
        })
        print(f"[DEBUG] تم حفظ بيانات الرحلة الأخيرة للتعديل: {car_type}")
        
    def _detect_modification_type_and_location(self, query: str) -> dict:
        """تحديد نوع التعديل (بداية/نهاية) والموقع الجديد"""
        
        prompt = f"""
        المستخدم يريد تعديل رحلته الحالية: "{query}"
        
        حدد:
        1. نوع التعديل: هل يريد تغيير "البداية" أم "النهاية" أم "كليهما"؟
        2. الموقع الجديد: ما هو اسم المكان الجديد؟
        
        انتبه جيداً للحالات التالية:
        - إذا قال "من A إلى B" فهذا يعني تغيير كليهما: البداية إلى A والنهاية إلى B
        - إذا قال "غير الموقع ليصير من A إلى B" فهذا أيضاً يعني تغيير كليهما
        - إذا قال "بدي اعدل الرحلة لتصير من A الى B" فهذا تغيير كليهما
        - إذا قال "بدي اغير X و تصير Y" فهذا يعني تغيير البداية من X إلى Y
        - إذا قال "بدي اغير مكاني ليصير من X" فهذا يعني تغيير البداية إلى X
        - إذا قال "بدي اير الرحلة من X الى Y" فهذا يعني تغيير كليهما
        
        أمثلة:
        - "غير الوجهة للسلط" -> نوع: "النهاية", موقع: "السلط"
        - "بدي أغير البداية لعجلون" -> نوع: "البداية", موقع: "عجلون"
        - "خلاص صير من الزرقاء لعمان" -> نوع: "كليهما", بداية: "الزرقاء", نهاية: "عمان"
        - "بدي اعدل الرحلة لتصير من السلط الى الدار" -> نوع: "كليهما", بداية: "السلط", نهاية: "الدار"
        - "بدي اغير اربد و تصير السلط" -> نوع: "البداية", موقع: "السلط"
        - "بدي اغير مكاني ليصير من الرفيد" -> نوع: "البداية", موقع: "الرفيد"
        - "بدي اير الرحلة من العقبة الى الدار" -> نوع: "كليهما", بداية: "العقبة", نهاية: "الدار"
        - "غير المكان لإربد" -> نوع: "النهاية", موقع: "إربد"
        
        أرجع النتيجة بصيغة JSON صحيحة فقط بدون أي نص إضافي:
        {{
            "modification_type": "البداية" أو "النهاية" أو "كليهما",
            "new_start_location": "اسم المكان الجديد أو null",
            "new_end_location": "اسم المكان الجديد أو null"
        }}
        """
        
        try:
            response = self.llm.invoke(prompt)
            content = response.content.strip()
            
            # تنظيف المحتوى من أي نص إضافي
            if content.startswith('```json'):
                content = content.replace('```json', '').replace('```', '').strip()
            elif content.startswith('```'):
                content = content.replace('```', '').strip()
            
            # البحث عن JSON في النص
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            if json_start != -1 and json_end != -1:
                content = content[json_start:json_end]
            
            result = json.loads(content)
            print(f"[DEBUG] نتيجة تحليل التعديل: {result}")
            return result
        except Exception as e:
            print(f"[خطأ] في تحليل طلب التعديل: {e}")
            print(f"[DEBUG] محتوى الاستجابة: {response.content if 'response' in locals() else 'لا يوجد'}")
            # fallback: محاولة استخراج المواقع مباشرة
            return self._fallback_parse_locations(query)

    def _fallback_parse_locations(self, query: str) -> dict:
        """تحليل احتياطي لاستخراج المواقع من النص"""
        print(f"[DEBUG] استخدام التحليل الاحتياطي للنص: {query}")
        
        # البحث عن نمط "من X إلى Y" أو "من X لـ Y"
        patterns = [
            r'من\s+([^\s]+)\s+(?:إلى|الى|لـ|ل)\s+([^\s]+)',
            r'ليصبح\s+من\s+([^\s]+)\s+(?:إلى|الى|لـ|ل)\s+([^\s]+)',
            r'صير\s+من\s+([^\s]+)\s+(?:إلى|الى|لـ|ل)\s+([^\s]+)',
            r'لتصير\s+من\s+([^\s]+)\s+(?:إلى|الى|لـ|ل)\s+([^\s]+)',
            r'اير\s+الرحلة\s+من\s+([^\s]+)\s+(?:إلى|الى|لـ|ل)\s+([^\s]+)'  # إضافة هذا النمط
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query)
            if match:
                start_loc, end_loc = match.groups()
                print(f"[DEBUG] تم العثور على نمط كليهما: البداية={start_loc}, النهاية={end_loc}")
                return {
                    "modification_type": "كليهما",
                    "new_start_location": start_loc.strip(),
                    "new_end_location": end_loc.strip()
                }
        
        # البحث عن نمط "اغير X و تصير Y"
        change_pattern = r'اغير\s+([^\s]+)\s+و\s+تصير\s+([^\s]+)'
        match = re.search(change_pattern, query)
        if match:
            old_loc, new_loc = match.groups()
            print(f"[DEBUG] تم العثور على نمط تغيير البداية: من {old_loc} إلى {new_loc}")
            return {
                "modification_type": "البداية",
                "new_start_location": new_loc.strip(),
                "new_end_location": None
            }
        
        # البحث عن نمط "مكاني ليصير من X"
        start_change_pattern = r'مكاني\s+ليصير\s+من\s+([^\s]+)'
        match = re.search(start_change_pattern, query)
        if match:
            new_start = match.group(1)
            print(f"[DEBUG] تم العثور على نمط تغيير البداية: إلى {new_start}")
            return {
                "modification_type": "البداية",
                "new_start_location": new_start.strip(),
                "new_end_location": None
            }
        
        # إذا لم نجد نمط واضح، نحاول استخراج الموقع ونفترض تغيير الوجهة
        location = self._extract_location_from_query(query)
        print(f"[DEBUG] لم يتم العثور على نمط واضح، افتراض تغيير الوجهة إلى: {location}")
        return {
            "modification_type": "النهاية",
            "new_start_location": None,
            "new_end_location": location
        }

    def _extract_location_from_query(self, query: str) -> str:
        """استخراج اسم المكان من النص - fallback method"""
        # إزالة الكلمات الشائعة والبحث عن اسم المكان
        words_to_remove = ["بدل", "الدار", "بدي", "اروح", "الى", "من", "غير", "الوجهة", 
                          "للـ", "لـ", "ليصبح", "الموقع", "اغير", "تصير", "مكاني", "اير", "الرحلة"]
        words = query.split()
        location_words = [word for word in words if word not in words_to_remove and len(word) > 1]
        
        # إذا كان هناك كلمة واحدة فقط، استخدمها
        if len(location_words) == 1:
            return location_words[0]
        
        # إذا كان هناك عدة كلمات، حاول دمجها
        return " ".join(location_words) if location_words else query.strip()

    def _resolve_location(self, location_name: str) -> Location:
        """تحويل اسم المكان إلى كائن Location"""
        if not location_name:
            return None
        
        print(f"[DEBUG] محاولة تحويل الموقع: {location_name}")
        
        # استخدام نفس آلية معالجة المواقع المستخدمة في get_directions_tool
        # التحقق من المواقع المحفوظة أولاً
        saved_check = check_saved_locations(f"من هنا الى {location_name}")
        resolved_location = saved_check.get("end_location")
        
        if is_latlng(resolved_location):
            lat, lng = parse_latlng(resolved_location)
            display_name = get_location_name_from_coordinates(resolved_location)
            if display_name == resolved_location:
                display_name = location_name
            return Location(name=display_name, lat=lat, lng=lng)
        else:
            # استخدام geocoding للعناوين العادية
            resolved_name = resolved_location or location_name
            print(f"[DEBUG] البحث عن إحداثيات: {resolved_name}")
            lat, lng = resolve_address_to_coordinates(resolved_name)
            if lat is not None and lng is not None:
                print(f"[DEBUG] تم العثور على إحداثيات: {lat}, {lng}")
                return Location(name=resolved_name, lat=lat, lng=lng)
            else:
                print(f"[DEBUG] فشل في العثور على إحداثيات لـ: {resolved_name}")
        
        return None

    def _run(self, query: str) -> str:
        try:
            # التحقق من وجود رحلة سابقة
            if not hasattr(self, 'last_trip_data') or not self.last_trip_data:
                return "❌ لا توجد رحلة محفوظة للتعديل. يرجى طلب رحلة جديدة أولاً."

            print(f"[DEBUG] معالجة طلب التعديل: {query}")
            
            # تحليل طلب التعديل
            modification_info = self._detect_modification_type_and_location(query)
            mod_type = modification_info.get("modification_type")
            new_start_name = modification_info.get("new_start_location")
            new_end_name = modification_info.get("new_end_location")
            
            print(f"[DEBUG] نوع التعديل: {mod_type}")
            print(f"[DEBUG] البداية الجديدة: {new_start_name}")
            print(f"[DEBUG] النهاية الجديدة: {new_end_name}")
            
            # الحصول على بيانات الرحلة الحالية
            current_start = self.last_trip_data["start_location"]
            current_end = self.last_trip_data["end_location"]
            car_type = self.last_trip_data["car_type"]  # احتفظ بنوع السيارة الحالي
            
            print(f"[DEBUG] الرحلة الحالية: من {current_start.name} إلى {current_end.name}")
            print(f"[DEBUG] نوع السيارة الحالي المحفوظ: {car_type}")
            
            # تحديد المواقع الجديدة
            final_start_loc = current_start
            final_end_loc = current_end
            changes_made = []
            
            # معالجة التعديلات
            if mod_type == "البداية" or mod_type == "كليهما":
                if new_start_name:
                    new_start_loc = self._resolve_location(new_start_name)
                    if new_start_loc:
                        final_start_loc = new_start_loc
                        changes_made.append(f"البداية من '{current_start.name}' إلى '{new_start_loc.name}'")
                        print(f"[DEBUG] تم تحديث البداية إلى: {new_start_loc.name}")
                    else:
                        return f"❌ لم أتمكن من العثور على الموقع: '{new_start_name}'"
            
            if mod_type == "النهاية" or mod_type == "كليهما":
                if new_end_name:
                    new_end_loc = self._resolve_location(new_end_name)
                    if new_end_loc:
                        final_end_loc = new_end_loc
                        changes_made.append(f"الوجهة من '{current_end.name}' إلى '{new_end_loc.name}'")
                        print(f"[DEBUG] تم تحديث النهاية إلى: {new_end_loc.name}")
                    else:
                        return f"❌ لم أتمكن من العثور على الموقع: '{new_end_name}'"
            
            # التحقق من وجود تغييرات
            if not changes_made:
                return "❌ لم يتم تحديد أي تغييرات واضحة. يرجى المحاولة مرة أخرى."
            
            # التحقق من أن الرحلة ليست من نفس المكان إلى نفسه
            if (final_start_loc.lat == final_end_loc.lat and 
                final_start_loc.lng == final_end_loc.lng):
                return "❌ لا يمكن إنشاء رحلة من نفس المكان إلى نفسه. يرجى تحديد وجهة مختلفة."
            
            print(f"[DEBUG] الرحلة النهائية: من {final_start_loc.name} إلى {final_end_loc.name}")
            
            # إعادة حساب تفاصيل الرحلة مع الاحتفاظ بنوع السيارة الأصلي
            trip = compute_trip(final_start_loc, final_end_loc, car_type)
            
            # إنشاء معلومات الرحلة المحدثة
            trip_info = TripInfo(
                distance=trip.distance,
                duration=trip.duration,
                cost=trip.cost,
                car_type=car_type  # احتفظ بنوع السيارة الأصلي
            )
            
            # توليد بيانات السائق الجديد
            driver = generate_driver_location(final_start_loc, car_type)
            
            # تحديث بيانات الرحلة المحفوظة
            object.__setattr__(self, 'last_trip_data', {
                "start_location": final_start_loc,
                "end_location": final_end_loc,
                "car_type": car_type
            })
            
            # رسم الخريطة المحدثة
            map_info = ""
            try:
                map_filename = create_trip_map(
                    user_location={"lat": final_start_loc.lat, "lng": final_start_loc.lng},
                    driver_location={
                        "lat": driver['lat'], 
                        "lng": driver['lng'],
                        "distance_m": driver['distance_m'],
                        "arrival_time_min": driver['arrival_time_min'],
                        "car_type": car_type
                    },
                    destination_location={"lat": final_end_loc.lat, "lng": final_end_loc.lng},  
                    user_name="انس",
                    driver_name="ابو ثائر"
                )
                map_info = f"🗺️ تم إنشاء خريطة محدثة: {map_filename}"
            except Exception as e:
                print(f"DEBUG: خطأ في إنشاء الخريطة: {e}")
            
            # بناء الاستجابة
            response_lines = [
                "✅ تم تعديل الرحلة بنجاح!",
                "",
                "🔄 التغييرات المطبقة:"
            ]
            
            for change in changes_made:
                response_lines.append(f"   • {change}")
            
            response_lines.extend([
                "",
                "🚗 تفاصيل الرحلة المحدثة:",
                f"📍 من: {final_start_loc.name}",
                f"🎯 إلى: {final_end_loc.name}",
                f"🚖 السائق الجديد على بعد {driver['distance_m']} متر، سيصل خلال {driver['arrival_time_min']} دقيقة",
                f"⏱ الوقت المتوقع: {trip_info.duration}",
                f"📏 المسافة: {trip_info.distance}",
                f"💰 التكلفة المحدثة: {trip_info.cost} د.أ",
                f"🚘 نوع السيارة: {trip_info.car_type}"
            ])
            
            # إضافة ملاحظة السعر حسب نوع السيارة
            price_notes = {
                "عادية": "",
                "تاكسي": "📝 ملاحظة: (زيادة 15% للتاكسي)",
                "عائلية": "📝 ملاحظة: (زيادة 30% للسيارة العائلية)",
                "VIP": "📝ملاحظة: (زيادة 50% للسيارة المميزة)"
            }
            
            if car_type in price_notes and price_notes[car_type]:
                response_lines.append(price_notes[car_type])
            
            # إضافة معلومات الخريطة
            if map_info:
                response_lines.append("")
                response_lines.append(map_info)
            
            return "\n".join(response_lines)
            
        except Exception as e:
            print(f"[خطأ في تعديل الموقع] {str(e)}")
            return f"❌ عذراً، حدث خطأ أثناء تعديل الرحلة: {str(e)}"
    
    async def _arun(self, query: str) -> str:
        return self._run(query)