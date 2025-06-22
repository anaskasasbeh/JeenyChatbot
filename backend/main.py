import os
import argparse
from langchain.agents import initialize_agent, AgentType
from langchain_openai import ChatOpenAI 
from langchain.memory import ConversationBufferMemory
from tools.get_directions_tool import GetDirectionsTool
from tools.car_type_selector_tool import CarTypeSelectorTool
from tools.change_car_type_tool import ChangeCarTypeTool
from tools.modify_location_tool import ModifyLocationTool
from voice import recognize_speech, speak_arabic_response, test_voice_system
from dotenv import load_dotenv
from tools.get_directions_tool import get_shared_trip_data
from tools.get_directions_tool import set_shared_trip_data

# تحميل متغيرات البيئة
load_dotenv()

# إنشاء instances للأدوات للمشاركة بينها
get_directions_tool = GetDirectionsTool()
change_car_type_tool = ChangeCarTypeTool()
modify_location_tool = ModifyLocationTool()

# إعداد الذكاء الاصطناعي والأدوات
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
agent = initialize_agent(
    tools=[
        get_directions_tool,
        change_car_type_tool,
        modify_location_tool
    ],
    llm=llm,
    agent=AgentType.CONVERSATIONAL_REACT_DESCRIPTION,
    memory=memory,
    verbose=True
)

def sync_trip_data():
    """مزامنة بيانات الرحلة بين الأدوات - محدثة"""
    # محاولة الحصول على البيانات من أي أداة تحتوي على آخر رحلة
    shared_data = None
    
    # البحث عن البيانات في الأدوات
    shared_data = get_shared_trip_data()
    
    # إذا لم نجد بيانات في get_directions_tool، نحاول الحصول عليها من change_car_type_tool
    if not shared_data and hasattr(change_car_type_tool, 'last_trip_data') and change_car_type_tool.last_trip_data:
        shared_data = change_car_type_tool.last_trip_data
        print("[DEBUG] تم الحصول على البيانات من change_car_type_tool")
    
    # إذا لم نجد بيانات، نحاول الحصول عليها من modify_location_tool
    if not shared_data and hasattr(modify_location_tool, 'last_trip_data') and modify_location_tool.last_trip_data:
        shared_data = modify_location_tool.last_trip_data
        print("[DEBUG] تم الحصول على البيانات من modify_location_tool")
    
    if shared_data:
        # تحديث جميع الأدوات بنفس البيانات
        change_car_type_tool.set_last_trip(
            shared_data["start_location"],
            shared_data["end_location"], 
            shared_data["car_type"]
        )
        
        modify_location_tool.set_last_trip(
            shared_data["start_location"],
            shared_data["end_location"],
            shared_data["car_type"]
        )
        
        # تحديث البيانات المشتركة العامة
        set_shared_trip_data(
            shared_data["start_location"],
            shared_data["end_location"],
            shared_data["car_type"]
        )
        
        print(f"[DEBUG] تم مزامنة بيانات الرحلة: {shared_data['car_type']} من {shared_data['start_location'].name} إلى {shared_data['end_location'].name}")

def main():
    """الوظيفة الرئيسية للتطبيق"""
    parser = argparse.ArgumentParser(description="JeenyAgent - Smart Transportation Assistant")
    parser.add_argument('--use-voice', action='store_true', help='تشغيل خيار الصوت')
    parser.add_argument('--test-voice', action='store_true', help='اختبار نظام الصوت')
    args = parser.parse_args()

    if args.test_voice:
        test_voice_system()
        return

    print("👋 أهلاً بك في JeenyAgent - Smart Transportation Assistant")
    print("يمكنك:")
    print("• طلب رحلة: 'بدي سيارة من إربد لعمان'")
    print("• تغيير نوع السيارة: 'غير نوع السيارة لـ VIP'")
    print("• تعديل الوجهة: 'غير الوجهة للسلط'")
    print("• تعديل البداية: 'غير البداية لعجلون'")
    print("اكتب/قل 'شكرا لك' او 'انهي' او 'انهاء' او 'خروج' لإنهاء المحادثة")
    
    if args.use_voice:
        print("🎙️ تم تفعيل وضع الصوت للعربية")
        speak_arabic_response("مرحباً بك في نظام النقل الذكي")

    # الحلقة الرئيسية للمحادثة
    while True:
        try:
            # الحصول على إدخال المستخدم
            if args.use_voice:
                print("\n🎙️ انتظار الأمر الصوتي...")
                user_text = recognize_speech()
                if not user_text:
                    speak_arabic_response("لم أسمع شيئاً، حاول مرة أخرى")
                    continue
            else:
                user_text = input("\nأنت: ")
            
            # التحقق من أمر الإنهاء
            if user_text.strip().lower() in ['انهي', 'انهاء', 'خروج', 'exit', 'quit', 'شكرا لك']:
                goodbye_msg = "شكرًا لاستخدامك JeenyAgent. يومك سعيد!"
                print(f"👋 {goodbye_msg}")
                if args.use_voice:
                    speak_arabic_response(goodbye_msg)
                break
            
            # معالجة الطلب
            response = agent.invoke({"input": user_text})
            response_text = response["output"]
            print(f"🤖 {response_text}")
            
            # مزامنة بيانات الرحلة بعد كل استجابة
            sync_trip_data()
            
            # النطق الصوتي إذا كان مفعلاً
            if args.use_voice:
                speak_arabic_response(response_text)
                
        except KeyboardInterrupt:
            goodbye_msg = "تم إيقاف البرنامج. وداعاً!"
            print(f"\n👋 {goodbye_msg}")
            if args.use_voice:
                speak_arabic_response(goodbye_msg)
            break
        except Exception as e:
            error_msg = f"عذراً، حدث خطأ: {str(e)}"
            print(f"❌ {error_msg}")
            if args.use_voice:
                speak_arabic_response("عذراً، حدث خطأ في النظام")

if __name__ == '__main__':
    main()