from langchain.tools import BaseTool
from langchain_openai import ChatOpenAI
from typing import Optional
import json
import os
import re
from dotenv import load_dotenv

class CarTypeSelectorTool(BaseTool):
    name: str = "car_type_selector"
    description: str = (
        "تُستخدم هذه الأداة لتحديد نوع السيارة التي يفضلها المستخدم عند طلب رحلة. "
        "تعمل الأداة بعد تحديد نقطة الانطلاق والوجهة، وتساعد في تخصيص نوع السيارة. "
        "تشمل الأنواع: [1] عادية (4 ركاب)، [2] تاكسي، [3] سيارة عائلية (7 ركاب)، و[4] VIP."
    )
    
    def __init__(self):
        super().__init__()
        load_dotenv()  # تحميل متغيرات البيئة
        self._llm = None

    @property
    def llm(self):
        """Lazy loading للـ LLM"""
        if self._llm is None:
            self._llm = ChatOpenAI(
                model="gpt-4o-mini",
                temperature=0, 
                openai_api_key=os.getenv("OPENAI_API_KEY")
            )
        return self._llm

    def _detect_car_type_patterns(self, query: str) -> str:
        """استخدام regex patterns لتحديد نوع السيارة بدقة أكبر"""
        query_lower = query.lower()
        
        # أنماط للسيارة VIP
        vip_patterns = [
            r'vip',
            r'في آي بي',
            r'فاخرة',
            r'درجة أولى',
            r'ممتازة',
            r'كلاس عالي'
        ]
        
        # أنماط للسيارة العائلية
        family_patterns = [
            r'عائلية',
            r'عائلي',
            r'كبيرة',
            r'7 ركاب',
            r'سبع ركاب',
            r'سبعة ركاب',
            r'فان',
            r'باص صغير'
        ]
        
        # أنماط للتاكسي
        taxi_patterns = [
            r'تاكسي',
            r'تكسي',
            r'أجرة'
        ]
        
        # فحص الأنماط
        for pattern in vip_patterns:
            if re.search(pattern, query_lower):
                return "VIP"
                
        for pattern in family_patterns:
            if re.search(pattern, query_lower):
                return "عائلية"
                
        for pattern in taxi_patterns:
            if re.search(pattern, query_lower):
                return "تاكسي"
        
        return "عادية"  # القيمة الافتراضية

    def _run(self, query: str) -> str:
        # أولاً، جرب الكشف بالأنماط
        pattern_result = self._detect_car_type_patterns(query)
        if pattern_result != "عادية":
            print(f"[DEBUG] تم تحديد نوع السيارة بالأنماط: {pattern_result}")
            return pattern_result
        
        # إذا لم نجد نمط واضح، استخدم LLM مع prompt محسن
        prompt = f"""
        المستخدم يريد طلب سيارة: "{query}"
        
        حدد نوع السيارة من هذه الخيارات فقط:
        - عادية: إذا لم يذكر نوع محدد أو قال "عادية" أو "طبيعية"
        - تاكسي: إذا ذكر كلمة "تاكسي" أو "تكسي" أو "أجرة"
        - عائلية: إذا ذكر "عائلية" أو "كبيرة" أو "7 ركاب" أو "فان"
        - VIP: إذا ذكر "VIP" أو "فاخرة" أو "درجة أولى"
        
        أجب بكلمة واحدة فقط من الخيارات أعلاه.
        الافتراضي هو "عادية" إذا لم يحدد المستخدم نوعاً معيناً.
        """
        
        try:
            print(f"[DEBUG] Car type query: {query}")
            # الحصول على نوع السيارة من LLM
            response = self.llm.invoke(prompt).content.strip()
            print(f"[DEBUG] Car type LLM response: {response}")
            
            # التحقق من صحة الإجابة وتنظيفها
            valid_types = ["عادية", "تاكسي", "عائلية", "VIP"]
            
            # تنظيف الإجابة من علامات الترقيم والمسافات الزائدة
            clean_response = response.strip().replace('"', '').replace("'", "").replace('.', '')
            
            if clean_response in valid_types:
                return clean_response
            
            # محاولة البحث عن الكلمة داخل النص
            for car_type in valid_types:
                if car_type in response:
                    print(f"[DEBUG] وجدت نوع السيارة داخل النص: {car_type}")
                    return car_type
            
            # إذا لم نجد تطابق، استخدم الافتراضي
            print(f"[تحذير] نوع سيارة غير صحيح: {response}, استخدام الافتراضي")
            return "عادية"
            
        except Exception as e:
            print(f"[خطأ] في تحديد نوع السيارة: {e}")
            return "عادية"  # في حالة حدوث خطأ، استخدم القيمة الافتراضية

    async def _arun(self, query: str) -> str:
        return self._run(query)