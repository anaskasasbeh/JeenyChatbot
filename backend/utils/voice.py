import speech_recognition as sr
import pyttsx3
import os
import re
import time
import tempfile
from gtts import gTTS
import pygame

# متغيرات عامة للتحسين
_pygame_initialized = False
_tts_engine = None

def setup_voice_recognition():
    """إعداد محرك التعرف على الصوت"""
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = True
    recognizer.pause_threshold = 0.8
    return recognizer

def setup_pygame_audio():
    """إعداد pygame للصوت مع تحسين الأداء"""
    global _pygame_initialized
    if _pygame_initialized:
        return True
    
    try:
        pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
        _pygame_initialized = True
        return True
    except Exception as e:
        print(f"⚠️ تم تعطيل pygame audio: {e}")
        return False

def setup_local_tts():
    """إعداد محرك النطق المحلي مع تحسين الأداء"""
    global _tts_engine
    if _tts_engine:
        return _tts_engine
    
    try:
        engine = pyttsx3.init()
        voices = engine.getProperty('voices')
        
        # البحث عن أفضل صوت متاح
        best_voice = None
        for voice in voices:
            voice_name = voice.name.lower()
            voice_id = voice.id.lower()
            
            # أولوية للأصوات العربية
            if any(keyword in voice_name or keyword in voice_id 
                  for keyword in ['arabic', 'ar-', 'عربي']):
                best_voice = voice.id
                break
            # بديل: الأصوات النسائية
            elif any(keyword in voice_name 
                    for keyword in ['female', 'woman', 'zira', 'hazel']):
                best_voice = voice.id
        
        if best_voice:
            engine.setProperty('voice', best_voice)
            
        # إعداد سرعة وحجم الصوت
        engine.setProperty('rate', 120)
        engine.setProperty('volume', 0.95)
        
        _tts_engine = engine
        return engine
        
    except Exception as e:
        print(f"⚠️ خطأ في إعداد المحرك المحلي: {e}")
        return None

def recognize_speech():
    """تحويل الصوت إلى نص مع دعم محسّن للعربية"""
    recognizer = setup_voice_recognition()
    
    # قائمة اللغات بالترتيب الأمثل
    languages = ['ar-JO', 'ar-SA', 'ar-EG', 'ar', 'en-US']
    
    with sr.Microphone() as mic:
        print("🎙️ جاري ضبط الميكروفون...")
        recognizer.adjust_for_ambient_noise(mic, duration=1.5)
        print("🎙️ تحدث الآن...")
        
        try:
            audio = recognizer.listen(mic, timeout=15, phrase_time_limit=12)
            print("🎙️ جاري معالجة الصوت...")
            
            # محاولة التعرف بلغات متعددة
            for lang in languages:
                try:
                    text = recognizer.recognize_google(audio, language=lang)
                    if text.strip():
                        print(f"أنت: {text}")
                        return text
                except (sr.UnknownValueError, sr.RequestError):
                    continue
            
            print("❌ لم أتمكن من فهم الصوت، حاول مرة أخرى")
            return ""
                    
        except sr.WaitTimeoutError:
            print("⏰ انتهت مهلة الانتظار")
            return ""
        except Exception as e:
            print(f"❌ خطأ في تسجيل الصوت: {e}")
            return ""

def contains_arabic(text):
    """التحقق من وجود أحرف عربية"""
    return bool(re.search(r'[\u0600-\u06FF]', text))

def speak_with_gtts(text):
    """النطق باستخدام Google TTS"""
    try:
        if not setup_pygame_audio():
            return False
            
        # تحديد اللغة تلقائياً
        lang = 'ar' if contains_arabic(text) else 'en'
        
        # إنشاء TTS
        tts = gTTS(text=text, lang=lang, slow=False, tld='com')
        
        # إنشاء ملف مؤقت
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as temp_file:
            temp_path = temp_file.name
        
        try:
            # حفظ وتشغيل الملف الصوتي
            tts.save(temp_path)
            pygame.mixer.music.load(temp_path)
            pygame.mixer.music.play()
            
            # انتظار انتهاء التشغيل
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
            
            return True
            
        finally:
            # تنظيف الملف المؤقت
            try:
                os.unlink(temp_path)
            except:
                pass
                
    except Exception as e:
        print(f"⚠️ خطأ في Google TTS: {e}")
        return False

def speak_with_local_tts(text):
    """النطق باستخدام المحرك المحلي"""
    try:
        engine = setup_local_tts()
        if not engine:
            return False
        
        # إعدادات محسّنة للسرعة
        rate = 130 if contains_arabic(text) else 150
        engine.setProperty('rate', rate)
        engine.setProperty('volume', 0.9)
        
        # النطق
        engine.say(text)
        engine.runAndWait()
        
        return True
        
    except Exception as e:
        print(f"⚠️ خطأ في المحرك المحلي: {e}")
        return False

def clean_response_text(text):
    """تنظيف النص من الرموز والتنسيقات للنطق الصوتي"""
    # إزالة الرموز التعبيرية والرموز الخاصة
    text = re.sub(r'[🚗📍🎯🚖⏱📏💰🚘🗺️✅❌⚠️🎙️🔊👋🤖🔄🔗📖]', '', text)
    
    # تنظيف علامات الترقيم
    text = re.sub(r'[?!؟]', '.', text)
    text = re.sub(r'[،,;:]', ' ', text)
    text = re.sub(r'\([^)]*\)', '', text)
    text = re.sub(r'\[[^\]]*\]', '', text)
    text = re.sub(r'["""\'\'`#*_~`|\\]', '', text)
    
    # إزالة الروابط والمسارات
    text = re.sub(r'http[s]?://[^\s]+', '', text)
    text = re.sub(r'/[^\s]*', '', text)
    
    # تنظيف المسافات والأسطر
    text = re.sub(r'\n+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\.{2,}', '.', text)
    
    return text.strip()

def split_text_for_speech(text, max_length=200):
    """تقسيم النص بذكاء للنطق"""
    if len(text) <= max_length:
        return [text]
    
    # تقسيم على النقاط أولاً
    sentences = [s.strip() + '.' for s in text.split('.') if s.strip()]
    
    parts = []
    current_part = ""
    
    for sentence in sentences:
        if len(current_part) + len(sentence) > max_length:
            if current_part:
                parts.append(current_part.strip())
                current_part = sentence
            else:
                # الجملة طويلة جداً، قسمها
                words = sentence.split()
                temp_part = ""
                for word in words:
                    if len(temp_part) + len(word) > max_length:
                        if temp_part:
                            parts.append(temp_part.strip())
                            temp_part = word
                        else:
                            parts.append(word)
                    else:
                        temp_part += " " + word if temp_part else word
                if temp_part:
                    current_part = temp_part
        else:
            current_part += " " + sentence if current_part else sentence
    
    if current_part:
        parts.append(current_part.strip())
    
    return parts

def speak_arabic_response(response_text):
    """دالة محسنة للرد على استجابات JeenyAgent"""
    if not response_text or not response_text.strip():
        return
        
    clean_text = clean_response_text(response_text)
    if not clean_text:
        return
    
    print(f"🔊 النطق: {clean_text}")
    
    # تقسيم النص الطويل
    if len(clean_text) > 200:
        parts = split_text_for_speech(clean_text)
        for part in parts:
            speak(part, force_arabic=True)
            time.sleep(0.3)  # توقف قصير بين الأجزاء
    else:
        speak(clean_text, force_arabic=True)

def speak(text, force_arabic=True):
    """تحويل النص إلى صوت مع أولوية للعربية"""
    if not text or not text.strip():
        return
    
    text = text.strip()
    has_arabic = contains_arabic(text)
    
    # استخدام gTTS للنصوص العربية
    if has_arabic or force_arabic:
        if not speak_with_gtts(text):
            speak_with_local_tts(text)
    else:
        # للنصوص الإنجليزية، المحرك المحلي أولاً
        if not speak_with_local_tts(text):
            speak_with_gtts(text)

def test_voice_system():
    """اختبار مبسط لنظام الصوت"""
    print("🧪 اختبار نظام الصوت...")
    
    test_phrases = [
        "مرحباً، أنا مساعد النقل الذكي",
        "تم إنشاء خريطة الرحلة بنجاح",
        "Hello, this is a voice test"
    ]
    
    for phrase in test_phrases:
        print(f"\n🔊 اختبار: {phrase}")
        speak(phrase)
        time.sleep(0.5)
    
    # اختبار التعرف على الصوت
    print("\n🎙️ اختبار التعرف على الصوت...")
    print("قل شيئاً...")
    
    result = recognize_speech()
    if result:
        print(f"✅ تم التعرف على: {result}")
        speak_arabic_response(f"فهمت أنك قلت: {result}")
    else:
        print("❌ لم يتم التعرف على أي صوت")
        speak("لم أتمكن من فهم ما قلته")