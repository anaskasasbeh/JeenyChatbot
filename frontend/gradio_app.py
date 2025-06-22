import gradio as gr
import os
import sys
from typing import List, Tuple, Optional
import time

# إضافة مسار المشروع للاستيرادات
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# استيراد الأدوات المطلوبة مباشرة
from langchain.agents import initialize_agent, AgentType
from langchain_openai import ChatOpenAI 
from langchain.memory import ConversationBufferMemory
from tools.get_directions_tool import GetDirectionsTool, get_shared_trip_data, set_shared_trip_data
from tools.car_type_selector_tool import CarTypeSelectorTool
from tools.change_car_type_tool import ChangeCarTypeTool
from tools.modify_location_tool import ModifyLocationTool
from voice import recognize_speech, speak_arabic_response, test_voice_system
from dotenv import load_dotenv

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

def process_message(message: str, history: List[Tuple[str, str]], use_voice: bool = False) -> Tuple[str, List[Tuple[str, str]], str]:
    """معالجة الرسائل مع دعم الصوت الاختياري"""
    if not message.strip():
        return "", history or [], ""
    
    # التحقق من أمر الإنهاء
    if message.strip().lower() in ['انهي', 'انهاء', 'خروج', 'exit', 'quit', 'شكرا لك']:
        goodbye_msg = "شكرًا لاستخدامك JeenyAgent. يومك سعيد! 👋"
        history = history or []
        history.append((message, goodbye_msg))
        if use_voice:
            speak_arabic_response(goodbye_msg)
        return "", history, "تم إنهاء المحادثة"
    
    try:
        # تتبع الخرائط الموجودة قبل المعالجة
        import glob
        maps_before = set(glob.glob("maps/trip_map_*.html"))
        
        # معالجة الطلب مع Agent
        response = agent.invoke({"input": message})
        response_text = response["output"]
        
        # مزامنة بيانات الرحلة بعد كل استجابة
        sync_trip_data()
        
        # التحقق من إنشاء خريطة جديدة فقط
        maps_after = set(glob.glob("maps/trip_map_*.html"))
        new_maps = maps_after - maps_before
        
        map_info = ""
        if new_maps:
            # إذا تم إنشاء خريطة جديدة، أضفها للرد
            latest_map = max(new_maps, key=os.path.getctime)
            map_filename = os.path.basename(latest_map)
            map_info = f"\n\n🗺️ **[اضغط هنا لعرض الخريطة](file/{latest_map})**"
        
        final_response = response_text + map_info
        
        # النطق الصوتي إذا كان مفعل
        if use_voice:
            speak_arabic_response(response_text)
        
        status = "تم معالجة الطلب بنجاح ✅"
        
    except Exception as e:
        final_response = f"⚠️ عذراً، حدث خطأ: {str(e)}"
        status = f"حدث خطأ: {str(e)}"
        if use_voice:
            speak_arabic_response("عذراً، حدث خطأ في النظام")
    
    # تحديث التاريخ
    history = history or []
    history.append((message, final_response))
    
    return "", history, status

def voice_input_handler(history: List[Tuple[str, str]]) -> Tuple[str, List[Tuple[str, str]], str]:
    """معالج الإدخال الصوتي"""
    try:
        print("🎙️ بدء التسجيل الصوتي...")
        user_text = recognize_speech()
        
        if not user_text:
            error_msg = "🎙️ لم أتمكن من فهم الصوت، يرجى المحاولة مرة أخرى"
            return "", history, error_msg
        
        print(f"🎙️ تم التعرف على النص: {user_text}")
        
        # معالجة النص المسجل
        return process_message(user_text, history, use_voice=True)
        
    except Exception as e:
        error_msg = f"⚠️ خطأ في التسجيل الصوتي: {str(e)}"
        return "", history, error_msg

def clear_chat() -> Tuple[List, str, str]:
    """مسح المحادثة وإعادة تعيين الذاكرة"""
    global memory
    memory.clear()
    return [], "", "تم مسح المحادثة وإعادة تعيين الذاكرة ✨"

def get_example_queries() -> List[str]:    
    """أمثلة على الاستعلامات المحدثة"""
    return [
        "بدي أروح من إربد إلى عمان",
        "كم تكلفة الرحلة من الجامعة الأردنية إلى المطار؟",
        "بدي سيارة VIP من وسط البلد إلى العبدلي",
        "غير نوع السيارة لتاكسي",
        "غير الوجهة للسلط",
        "بدي أعدل الرحلة لتصير من الزرقاء إلى عجلون",
        "مساء الخير بدي انطلق من الدار الى الجامعة",
        "رايح من التكنو الى دار جدي يا حلو"
    ]

# CSS مبسط وفعال
custom_css = """
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@300;400;600;700&display=swap');

.gradio-container {
    direction: rtl !important;
    font-family: 'Cairo', sans-serif !important;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    min-height: 100vh;
}

.main-header {
    text-align: center;
    background: rgba(255,255,255,0.95);
    backdrop-filter: blur(10px);
    border-radius: 20px;
    padding: 30px;
    margin: 20px;
    box-shadow: 0 15px 35px rgba(0,0,0,0.1);
}

.main-title {
    background: linear-gradient(45deg, #667eea, #764ba2);
    background-clip: text;
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-size: 2.5rem;
    font-weight: 700;
    margin-bottom: 10px;
}

.chat-container {
    background: rgba(255,255,255,0.95) !important;
    backdrop-filter: blur(10px) !important;
    border-radius: 20px !important;
    box-shadow: 0 15px 35px rgba(0,0,0,0.1) !important;
    border: none !important;
}

.input-row {
    background: rgba(255,255,255,0.9);
    backdrop-filter: blur(10px);
    border-radius: 25px;
    padding: 15px;
    margin: 10px;
    box-shadow: 0 10px 25px rgba(0,0,0,0.1);
}

.custom-button {
    background: linear-gradient(45deg, #667eea, #764ba2) !important;
    border: none !important;
    border-radius: 15px !important;
    color: white !important;
    font-weight: 600 !important;
    font-family: 'Cairo', sans-serif !important;
    padding: 12px 20px !important;
    transition: all 0.3s ease !important;
    box-shadow: 0 5px 15px rgba(102, 126, 234, 0.3) !important;
}

.custom-button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 25px rgba(102, 126, 234, 0.4) !important;
}

.voice-button {
    background: linear-gradient(45deg, #ff6b6b, #ee5a24) !important;
    box-shadow: 0 5px 15px rgba(255, 107, 107, 0.3) !important;
}

.voice-button:hover {
    box-shadow: 0 8px 25px rgba(255, 107, 107, 0.4) !important;
}

.examples-container {
    background: rgba(255,255,255,0.9);
    backdrop-filter: blur(10px);
    border-radius: 15px;
    padding: 20px;
    margin: 10px;
    box-shadow: 0 10px 25px rgba(0,0,0,0.1);
}

.status-message {
    text-align: center;
    padding: 10px;
    border-radius: 10px;
    margin: 10px;
    font-weight: 500;
    background: rgba(255,255,255,0.9);
    backdrop-filter: blur(10px);
}

.status-success {
    background: rgba(34, 197, 94, 0.1);
    color: #059669;
    border: 1px solid rgba(34, 197, 94, 0.3);
}

.status-error {
    background: rgba(239, 68, 68, 0.1);
    color: #dc2626;
    border: 1px solid rgba(239, 68, 68, 0.3);
}

@media (max-width: 768px) {
    .main-title {
        font-size: 2rem !important;
    }
    .main-header {
        padding: 20px;
        margin: 10px;
    }
}
"""

def create_interface():
    """إنشاء واجهة Gradio المحسنة"""
    
    # إنشاء مجلد الخرائط إذا لم يكن موجود
    if not os.path.exists("maps"):
        os.makedirs("maps")
    
    with gr.Blocks(
        css=custom_css, 
        title="🚗 JeenyAgent - مساعدك الذكي للنقل",
        theme=gr.themes.Soft(
            primary_hue="blue",
            secondary_hue="purple",
            neutral_hue="slate",
            font=gr.themes.GoogleFont("Cairo")
        )
    ) as demo:
        
        # العنوان الرئيسي
        with gr.Row():
            with gr.Column():
                gr.HTML("""
                    <div class="main-header">
                        <h1 class="main-title">🚗 JeenyAgent</h1>
                        <p style="color: #666; font-size: 1.2rem; margin: 0;">
                            مساعدك الذكي للنقل والمواصلات
                        </p>
                        <p style="color: #888; font-size: 0.9rem; margin-top: 10px;">
                            🎙️ دعم كامل للأوامر الصوتية والنصية | 🔄 تعديل الرحلات | 🚗 تغيير نوع السيارة
                        </p>
                    </div>
                """)
        
        # منطقة الدردشة
        with gr.Row():
            with gr.Column():
                chatbot = gr.Chatbot(
                    elem_classes=["chat-container"],
                    height=500,
                    show_label=False,
                    avatar_images=("👤", "🤖"),
                    bubble_full_width=False,
                    show_copy_button=True,
                    layout="bubble",
                    likeable=True,
                    rtl=True
                )
        
        # منطقة الإدخال والأزرار
        with gr.Row(elem_classes=["input-row"]):
            with gr.Column(scale=6):
                msg = gr.Textbox(
                    show_label=False,
                    placeholder="💬 اكتب رسالتك هنا... (مثلاً: بدي أروح من إربد لعمان، أو غير نوع السيارة لـ VIP)",
                    lines=2,
                    container=False,
                    rtl=True
                )
            
            with gr.Column(scale=2):
                with gr.Row():
                    send_btn = gr.Button(
                        "📤 إرسال", 
                        elem_classes=["custom-button"],
                        size="sm"
                    )
                with gr.Row():
                    voice_btn = gr.Button(
                        "🎙️ صوت", 
                        elem_classes=["custom-button", "voice-button"],
                        size="sm"
                    )
            
            with gr.Column(scale=1):
                clear_btn = gr.Button(
                    "🗑️ مسح", 
                    elem_classes=["custom-button"],
                    size="sm",
                    variant="secondary"
                )
        
        # رسالة الحالة
        status_msg = gr.Textbox(
            show_label=False,
            interactive=False,
            container=False,
            visible=True,
            elem_classes=["status-message"],
            placeholder="أهلاً بك! يمكنك البدء بطلب رحلة أو تعديل رحلة موجودة"
        )
        
        # أمثلة سريعة
        with gr.Row():
            with gr.Column():
                gr.HTML("""
                    <div class="examples-container">
                        <h3 style="color: #667eea; margin-bottom: 15px; text-align: center;">
                            ✨ أمثلة سريعة - اضغط لتجربة
                        </h3>
                    </div>
                """)
                
                examples = gr.Examples(
                    examples=get_example_queries(),
                    inputs=msg,
                    label=""
                )
        
        # معلومات الميزات المحدثة
        with gr.Row():
            with gr.Column():
                gr.HTML("""
                    <div class="examples-container">
                        <h4 style="color: #764ba2; margin-bottom: 15px; text-align: center;">
                            🎯 ما يمكنني مساعدتك به
                        </h4>
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;">
                            <div style="text-align: center; padding: 15px; background: linear-gradient(45deg, #667eea, #764ba2); color: white; border-radius: 10px;">
                                <div style="font-size: 2rem;">🗺️</div>
                                <strong>حساب المسارات</strong><br>
                                <small>من أي مكان إلى أي مكان في الأردن</small>
                            </div>
                            <div style="text-align: center; padding: 15px; background: linear-gradient(45deg, #764ba2, #667eea); color: white; border-radius: 10px;">
                                <div style="font-size: 2rem;">💰</div>
                                <strong>حساب التكلفة</strong><br>
                                <small>تقدير دقيق لتكلفة الرحلة</small>
                            </div>
                            <div style="text-align: center; padding: 15px; background: linear-gradient(45deg, #667eea, #764ba2); color: white; border-radius: 10px;">
                                <div style="font-size: 2rem;">🚗</div>
                                <strong>أنواع السيارات</strong><br>
                                <small>عادية، تاكسي، عائلية، VIP</small>
                            </div>
                            <div style="text-align: center; padding: 15px; background: linear-gradient(45deg, #764ba2, #667eea); color: white; border-radius: 10px;">
                                <div style="font-size: 2rem;">🔄</div>
                                <strong>تعديل الرحلات</strong><br>
                                <small>غير البداية، الوجهة، أو نوع السيارة</small>
                            </div>
                            <div style="text-align: center; padding: 15px; background: linear-gradient(45deg, #667eea, #764ba2); color: white; border-radius: 10px;">
                                <div style="font-size: 2rem;">🎙️</div>
                                <strong>الأوامر الصوتية</strong><br>
                                <small>تحدث بصوتك وسيفهمك المساعد</small>
                            </div>
                            <div style="text-align: center; padding: 15px; background: linear-gradient(45deg, #764ba2, #667eea); color: white; border-radius: 10px;">
                                <div style="font-size: 2rem;">🚖</div>
                                <strong>معلومات السائق</strong><br>
                                <small>موقع السائق ووقت الوصول</small>
                            </div>
                        </div>
                        <div style="margin-top: 20px; padding: 15px; background: rgba(102, 126, 234, 0.1); border-radius: 10px; border-right: 4px solid #667eea;">
                            <h5 style="color: #667eea; margin: 0 0 10px 0;">💡 أمثلة على الأوامر الجديدة:</h5>
                            <ul style="margin: 0; padding-right: 20px; color: #666;">
                                <li>"غير نوع السيارة لـ VIP"</li>
                                <li>"غير الوجهة للسلط"</li>
                                <li>"بدي أعدل الرحلة من الزرقاء إلى عجلون"</li>
                                <li>"خلاص صير من الدار إلى الجامعة"</li>
                            </ul>
                        </div>
                    </div>
                """)
        
        # ربط الأحداث
        # الإرسال النصي
        msg.submit(
            lambda m, h: process_message(m, h, use_voice=False), 
            inputs=[msg, chatbot], 
            outputs=[msg, chatbot, status_msg]
        )
        
        send_btn.click(
            lambda m, h: process_message(m, h, use_voice=False), 
            inputs=[msg, chatbot], 
            outputs=[msg, chatbot, status_msg]
        )
        
        # الإدخال الصوتي
        voice_btn.click(
            voice_input_handler, 
            inputs=[chatbot], 
            outputs=[msg, chatbot, status_msg]
        )
        
        # مسح المحادثة
        clear_btn.click(clear_chat, outputs=[chatbot, msg, status_msg])
        
        return demo

if __name__ == "__main__":
    print("🚀 تشغيل JeenyAgent المحسن مع الأدوات الجديدة...")
    print("🌐 الواجهة ستفتح على: http://localhost:7860")
    print("🎙️ دعم كامل للأوامر الصوتية")
    print("🔄 دعم تعديل الرحلات وتغيير نوع السيارة")
    
    # إنشاء الواجهة وتشغيلها
    demo = create_interface()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        inbrowser=True,
        share=False,
        show_error=True
    )