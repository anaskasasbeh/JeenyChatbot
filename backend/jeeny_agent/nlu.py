import os
import json
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from typing import Dict, Optional
import time
import re
from functools import lru_cache 

# إعداد مفاتيح API
load_dotenv()
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, openai_api_key=os.getenv("OPENAI_API_KEY"))

# تحميل الأماكن المحفوظة - إصلاح المسار
def load_saved_locations() -> dict:
    try:
        # الحصول على مجلد المشروع الحالي
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # الرجوع للمجلد الأب (backend) والوصول لملف saved_locations.json
        file_path = os.path.join(current_dir, '..', 'saved_locations.json')
        
        # طباعة المسار للتأكد (يمكن حذفها لاحقاً)
        print(f"[DEBUG] محاولة تحميل الملف من: {os.path.abspath(file_path)}")
        
        if not os.path.exists(file_path):
            print(f"[خطأ] الملف غير موجود: {file_path}")
            return {}
            
        with open(file_path, 'r', encoding='utf-8') as f:
            saved_data = json.load(f)
            print(f"[نجح] تم تحميل {len(saved_data)} موقع محفوظ")
            return saved_data
    except Exception as e:
        print(f"[خطأ] تعذر تحميل ملف الأماكن المحفوظة: {e}")
        return {}

# استخراج المواقع من النص
def extract_locations(user_text: str) -> dict:
    prompt = f"""
    أنت مساعد ذكي. المستخدم يتحدث باللهجة الأردنية ويعطيك جملة فيها موقعه الحالي والمكان الذي يريد الذهاب إليه.
    مهمتك استخراج:
    - نقطة البداية (start_location)
    - نقطة الوجهة (end_location)
    - الدولة (ثابتة: الأردن)
    
    النص:
    \"{user_text}\"    
الرجاء إرجاع النتيجة بصيغة JSON  بدون كتابة كلمة JSON حتى ، فقط مثل :
    {{
        "start_location": "",
        "end_location": "",
        "country": "الأردن"
    }}
    """
    try:
        response = llm.invoke(prompt)
        print(f"[DEBUG] Response content: {response.content}")  # Debug print
        # تحقق إذا كانت الاستجابة تحتوي على بيانات JSON صالحة
        if response.content.strip():
            result = json.loads(response.content)
            return result
        else:
            return {"error": "لم يتم استخراج المواقع بنجاح من النص."}
    except Exception as e:
        result = {"error": f"لم يتمكن النموذج من استخراج المواقع بدقة. [{e}]"}
        return result

# مقارنة المواقع مع الأماكن المحفوظة - تحسين الخوارزمية
def match_location_with_ai(user_place: str, saved_locations: dict) -> str:
    # إذا كان المكان فارغ، إرجاع كما هو
    if not user_place or not user_place.strip():
        return user_place
    
    # تنظيف النص
    user_place_clean = user_place.strip()
    
    # البحث المباشر أولاً
    if user_place_clean in saved_locations:
        matched_value = saved_locations[user_place_clean]
        print(f"[DEBUG] تم العثور على تطابق مباشر: {user_place_clean} -> {matched_value}")
        
        # إذا كانت القيمة المطابقة هي إحداثيات، نعيدها كما هي
        if is_latlng(matched_value):
            print(f"[DEBUG] القيمة المطابقة هي إحداثيات: {matched_value}")
            return matched_value
        else:
            print(f"[DEBUG] القيمة المطابقة هي اسم: {matched_value}")
            return matched_value
    
    # البحث بالكلمات المفتاحية
    for saved_key, saved_value in saved_locations.items():
        if saved_key.lower() in user_place_clean.lower() or user_place_clean.lower() in saved_key.lower():
            print(f"[DEBUG] تم العثور على تطابق جزئي: {saved_key} -> {saved_value}")
            return saved_value
    
    # استخدام AI للمطابقة الذكية
    location_names = list(saved_locations.keys())
    locations_str = "\n".join(f"- {loc}" for loc in location_names)
    
    prompt = f"""
    المستخدم قال إنه يريد الذهاب إلى: "{user_place_clean}"
    هذه قائمة بأسماء أماكن محفوظة موجودة في قاعدة البيانات:
    {locations_str}
    
    اختر أنسب مكان من القائمة يتطابق مع ما قاله المستخدم (بناءً على الفهم وليس التطابق الحرفي).
    إذا لم تجد تطابق واضح، قل فقط: NO_MATCH
    أجب فقط باسم المكان من القائمة أو كلمة NO_MATCH.
    """
    
    try:
        response = llm.invoke(prompt)
        choice = response.content.strip()
        print(f"[DEBUG] AI اختار: {choice}")
        
        if choice == "NO_MATCH" or choice not in location_names:
            return user_place_clean
        
        return saved_locations.get(choice, user_place_clean)
    except Exception as e:
        print(f"[تحذير] خطأ في AI matching: {e}")
        return user_place_clean

# التحقق من المواقع المحفوظة
def check_saved_locations(user_text: str) -> dict:
    print(f"[DEBUG] معالجة النص: {user_text}")
    
    extracted = extract_locations(user_text)
    if "error" in extracted:
        return extracted
    
    print(f"[DEBUG] المواقع المستخرجة: {extracted}")
    
    saved_locations = load_saved_locations()
    print(f"[DEBUG] عدد المواقع المحفوظة: {len(saved_locations)}")
    
    start_location = match_location_with_ai(extracted.get("start_location", ""), saved_locations)
    end_location = match_location_with_ai(extracted.get("end_location", ""), saved_locations)
    
    print(f"[DEBUG] الموقع المطابق للبداية: {start_location}")
    print(f"[DEBUG] الموقع المطابق للنهاية: {end_location}")
    
    return {
        "start_location": start_location,
        "end_location": end_location,
        "country": extracted.get("country", "الأردن")
    }

# دمج استخراج المواقع مع التحقق من الأماكن المحفوظة
def process_user_input(user_text: str) -> Dict:
    extracted = extract_locations(user_text)
    if "error" in extracted:
        return extracted
    
    enriched = check_saved_locations(extracted)
    return enriched if "error" not in enriched else extracted

# التحقق من تنسيق إحداثيات الموقع
def is_latlng(value: str) -> bool:
    if not value:
        return False
    # تحسين التحقق من الإحداثيات
    pattern = r'^\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*$'
    return bool(re.match(pattern, str(value).strip()))

# تحويل إحداثيات الموقع إلى معالم
def parse_latlng(latlng_str):
    try:
        parts = str(latlng_str).strip().split(",")
        if len(parts) == 2:
            lat = float(parts[0].strip())
            lng = float(parts[1].strip())
            return lat, lng
    except ValueError:
        pass
    return None, None

# تحويل الإحداثيات إلى اسم الموقع
def get_location_name_from_coordinates(latlng: str) -> str:
    if not latlng:
        return latlng
        
    saved_locations = load_saved_locations()
    for name, value in saved_locations.items():
        if str(value).strip() == str(latlng).strip():
            return name
    return latlng