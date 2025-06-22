import folium
from folium.map import Icon
from folium import plugins
import polyline
from googlemaps import Client
import os
import webbrowser
from datetime import datetime, timedelta
import random
import math
import sys
import subprocess
import platform
import json

gmaps = Client(key=os.getenv("GOOGLE_API_KEY"))

def get_car_icon(car_type):
    """تحديد أيقونة السيارة حسب النوع"""
    car_icons = {
        "عادية": {"icon": "car", "color": "green", "prefix": "fa"},
        "عائلية": {"icon": "users", "color": "blue", "prefix": "fa"},
        "VIP": {"icon": "star", "color": "purple", "prefix": "fa"},
        "تاكسي": {"icon": "taxi", "color": "orange", "prefix": "fa"}
    }
    return car_icons.get(car_type, {"icon": "car", "color": "green", "prefix": "fa"})

def calculate_distance_km(lat1, lng1, lat2, lng2):
    """حساب المسافة بالكيلومترات بين نقطتين"""
    R = 6371  # نصف قطر الأرض بالكيلومتر
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lng = math.radians(lng2 - lng1)
    
    a = (math.sin(delta_lat/2) * math.sin(delta_lat/2) +
         math.cos(lat1_rad) * math.cos(lat2_rad) *
         math.sin(delta_lng/2) * math.sin(delta_lng/2))
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c

def estimate_trip_cost(distance_km, car_type="عادية"):
    """تقدير تكلفة الرحلة"""
    base_rates = {
        "عادية": {"base": 1.5, "per_km": 0.8},
        "عائلية": {"base": 2.0, "per_km": 1.0},
        "VIP": {"base": 3.0, "per_km": 1.5},
        "تاكسي": {"base": 1.0, "per_km": 0.7}
    }
    
    rate = base_rates.get(car_type, base_rates["عادية"])
    cost = rate["base"] + (distance_km * rate["per_km"])
    return round(cost, 2)

def get_weather_info():
    """محاكاة معلومات الطقس - يمكن ربطها بـ API حقيقي لاحقاً"""
    weather_conditions = ["مشمس ☀️", "غائم جزئياً ⛅", "غائم ☁️", "مطر خفيف 🌧️"]
    return {
        "condition": random.choice(weather_conditions),
        "temp": random.randint(18, 35)
    }

def find_nearby_roads(user_location, distance_meters):
    """البحث عن طرق قريبة من المستخدم لوضع السائق عليها"""
    try:
        nearby_places = gmaps.places_nearby(
            location=(user_location['lat'], user_location['lng']),
            radius=min(distance_meters * 2, 1000),
            type='point_of_interest'
        )
        
        if nearby_places and 'results' in nearby_places:
            for place in nearby_places['results'][:5]:
                place_location = place['geometry']['location']
                place_distance = calculate_distance_km(
                    user_location['lat'], user_location['lng'],
                    place_location['lat'], place_location['lng']
                ) * 1000
                
                if abs(place_distance - distance_meters) < distance_meters * 0.5:
                    return {"lat": place_location['lat'], "lng": place_location['lng']}
    except:
        pass
    
    return None

def calculate_realistic_driver_position(user_location, destination_location, distance_meters):
    """حساب موقع السائق بطريقة واقعية ودقيقة"""
    try:
        road_position = find_nearby_roads(user_location, distance_meters)
        if road_position:
            actual_distance = calculate_distance_km(
                user_location['lat'], user_location['lng'],
                road_position['lat'], road_position['lng']
            ) * 1000
            print(f"[نجح] وُجد طريق قريب - المسافة: {actual_distance:.0f}م")
            return road_position
        
        distance_km = distance_meters / 1000.0
        
        if distance_meters <= 2000:
            lat_per_m = 1.0 / 111000.0
            lng_per_m = 1.0 / (111000.0 * math.cos(math.radians(user_location["lat"])))
            
            angle = random.uniform(0, 2 * math.pi)
            lat_offset = distance_meters * lat_per_m * math.sin(angle) * 0.8
            lng_offset = distance_meters * lng_per_m * math.cos(angle) * 0.8
            
            calculated_position = {
                "lat": user_location["lat"] + lat_offset,
                "lng": user_location["lng"] + lng_offset
            }
            
            return calculated_position
        
        else:
            for angle in [0, 45, 90, 135, 180, 225, 270, 315]:
                try:
                    temp_lat = user_location["lat"] + (distance_km / 111.0) * math.sin(math.radians(angle)) * 0.5
                    temp_lng = user_location["lng"] + (distance_km / (111.0 * math.cos(math.radians(user_location["lat"])))) * math.cos(math.radians(angle)) * 0.5
                    
                    directions = gmaps.directions(
                        origin=f"{temp_lat},{temp_lng}",
                        destination=f"{user_location['lat']},{user_location['lng']}",
                        mode="driving",
                        language="ar"
                    )
                    
                    if directions:
                        route_points = polyline.decode(directions[0]['overview_polyline']['points'])
                        if len(route_points) > 3:
                            selected_point = route_points[1]
                            return {"lat": selected_point[0], "lng": selected_point[1]}
                            
                except:
                    continue
            
            lat_offset = (distance_meters / 111000.0) * random.choice([-0.3, 0.3])
            lng_offset = (distance_meters / (111000.0 * math.cos(math.radians(user_location["lat"])))) * random.choice([-0.3, 0.3])
            
            return {
                "lat": user_location["lat"] + lat_offset,
                "lng": user_location["lng"] + lng_offset
            }
        
    except Exception as e:
        print(f"خطأ في حساب موقع السائق: {e}")
        return {
            "lat": user_location["lat"] + 0.002 * random.choice([-1, 1]),
            "lng": user_location["lng"] + 0.002 * random.choice([-1, 1])
        }

def open_file_in_browser(filepath):
    """فتح ملف في المتصفح بطريقة موثوقة"""
    try:
        system = platform.system().lower()
        abs_path = os.path.abspath(filepath)
        
        if system == "windows":
            try:
                os.startfile(abs_path)
                return True
            except:
                try:
                    subprocess.run(['start', '', abs_path], shell=True, check=True)
                    return True
                except:
                    pass
        
        elif system == "darwin":
            try:
                subprocess.run(['open', abs_path], check=True)
                return True
            except:
                pass
        
        elif system == "linux":
            try:
                subprocess.run(['xdg-open', abs_path], check=True)
                return True
            except:
                pass
        
        file_url = f"file://{abs_path.replace(os.sep, '/')}"
        webbrowser.open(file_url)
        return True
        
    except Exception as e:
        print(f"[تحذير] فشل في فتح الملف: {e}")
        return False

def create_trip_map(user_location, driver_location, destination_location, user_name="الراكب", driver_name="السائق"):
    try:
        # حساب المركز المثالي للخريطة
        all_lats = [user_location["lat"], driver_location["lat"], destination_location["lat"]]
        all_lngs = [user_location["lng"], driver_location["lng"], destination_location["lng"]]
        center_lat = sum(all_lats) / len(all_lats)
        center_lng = sum(all_lngs) / len(all_lngs)
        
        # إنشاء الخريطة بتصميم مبسط وسريع
        trip_map = folium.Map(
            location=[center_lat, center_lng], 
            zoom_start=13,
            tiles=None,  # بدء بدون tiles للتحكم الكامل
            prefer_canvas=True,  # تحسين الأداء
            control_scale=True
        )
        
        # إضافة طبقات الخرائط المحسنة مع ترتيب أفضل
        # الخريطة الأساسية (افتراضية)
        folium.TileLayer(
            tiles='OpenStreetMap',
            name='🗺️ عادية',
            control=True
        ).add_to(trip_map)
        
        # خريطة الأقمار الصناعية
        folium.TileLayer(
            tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
            attr='Google Satellite',
            name='🛰️ أقمار صناعية',
            control=True
        ).add_to(trip_map)
        
        # خريطة التضاريس
        folium.TileLayer(
            tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Terrain_Base/MapServer/tile/{z}/{y}/{x}',
            attr='Esri World Terrain',
            name='🏔️ تضاريس',
            control=True
        ).add_to(trip_map)
        
        # الوضع الليلي
        folium.TileLayer(
            tiles='CartoDB dark_matter',
            name='🌙 ليلي',
            control=True
        ).add_to(trip_map)
        
        # حساب معلومات الرحلة
        car_type = driver_location.get('car_type', 'عادية')
        car_icon_info = get_car_icon(car_type)
        
        # إعادة حساب موقع السائق
        realistic_driver_pos = calculate_realistic_driver_position(
            user_location, 
            destination_location, 
            driver_location.get('distance_m', 500)
        )
        
        driver_location["lat"] = realistic_driver_pos["lat"]
        driver_location["lng"] = realistic_driver_pos["lng"]
        
        # حساب المسافات والتكاليف
        driver_distance = calculate_distance_km(
            user_location["lat"], user_location["lng"],
            driver_location["lat"], driver_location["lng"]
        ) * 1000
        
        trip_distance = calculate_distance_km(
            user_location["lat"], user_location["lng"],
            destination_location["lat"], destination_location["lng"]
        )
        
        estimated_cost = estimate_trip_cost(trip_distance, car_type)
        weather = get_weather_info()
        
        # معلومات الوقت
        current_time = datetime.now()
        arrival_time = current_time + timedelta(minutes=driver_location.get('arrival_time_min', 5))
        
        # إضافة النقاط مع معلومات تفاعلية محسنة
        
        # marker المستخدم مع معلومات شاملة
        user_popup = f"""
        <div style="font-family: 'Segoe UI', Arial; font-size: 13px; width: 300px;">
            <div style="background: linear-gradient(135deg, #2196F3, #1976D2); color: white; padding: 12px; margin: -9px -9px 10px -9px; border-radius: 8px 8px 0 0;">
                <h3 style="margin: 0; text-align: center;">👤 {user_name}</h3>
            </div>
            
            <div style="padding: 8px;">
                <p style="margin: 5px 0;"><strong>📍 الموقع:</strong> نقطة الانطلاق</p>
                <p style="margin: 5px 0;"><strong>⏰ الوقت:</strong> {current_time.strftime('%H:%M')}</p>
                <p style="margin: 5px 0;"><strong>🌤️ الطقس:</strong> {weather['condition']} ({weather['temp']}°C)</p>
                
                <hr style="margin: 10px 0; border: 1px solid #eee;">
                
                <div style="background: #f8f9fa; padding: 8px; border-radius: 5px; margin: 8px 0;">
                    <p style="margin: 3px 0; font-size: 12px;"><strong>📊 معلومات الرحلة:</strong></p>
                    <p style="margin: 3px 0; font-size: 12px;">🛣️ المسافة: {trip_distance:.1f} كم</p>
                    <p style="margin: 3px 0; font-size: 12px;">💰 التكلفة المتوقعة: {estimated_cost} د.أ</p>
                </div>
                
                <div style="text-align: center; background: #e3f2fd; padding: 6px; border-radius: 5px; margin-top: 8px;">
                    <span style="color: #1976d2; font-weight: bold;">🔵 في انتظار السائق</span>
                </div>
            </div>
        </div>
        """
        
        folium.Marker(
            [user_location["lat"], user_location["lng"]],
            tooltip=f"📍 {user_name} - نقطة الانطلاق",
            popup=folium.Popup(user_popup, max_width=320),
            icon=Icon(color="blue", icon="user", prefix="fa")
        ).add_to(trip_map)
        
        # marker السائق مع معلومات مفصلة
        driver_popup = f"""
        <div style="font-family: 'Segoe UI', Arial; font-size: 13px; width: 320px;">
            <div style="background: linear-gradient(135deg, #4CAF50, #388E3C); color: white; padding: 12px; margin: -9px -9px 10px -9px; border-radius: 8px 8px 0 0;">
                <h3 style="margin: 0; text-align: center;">🚗 {driver_name}</h3>
            </div>
            
            <div style="padding: 8px;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                    <div style="flex: 1;">
                        <p style="margin: 3px 0;"><strong>🚘 السيارة:</strong> {car_type}</p>
                        <p style="margin: 3px 0;"><strong>📏 المسافة:</strong> {int(driver_distance)} متر</p>
                    </div>
                    <div style="flex: 1;">
                        <p style="margin: 3px 0;"><strong>⏱️ وقت الوصول:</strong> {driver_location.get('arrival_time_min', 5)} دقيقة</p>
                        <p style="margin: 3px 0;"><strong>🕒 سيصل الساعة:</strong> {arrival_time.strftime('%H:%M')}</p>
                    </div>
                </div>
                
                <hr style="margin: 10px 0; border: 1px solid #eee;">
                
                <div style="background: #f1f8e9; padding: 8px; border-radius: 5px; margin: 8px 0;">
                    <p style="margin: 3px 0; font-size: 12px;"><strong>🎯 معلومات إضافية:</strong></p>
                    <p style="margin: 3px 0; font-size: 12px;">⭐ تقييم: 4.8/5</p>
                    <p style="margin: 3px 0; font-size: 12px;">🚗 رقم اللوحة: ABC-123</p>
                    <p style="margin: 3px 0; font-size: 12px;">📱 رقم الهاتف: 079-XXX-XXXX</p>
                </div>
                
                <div style="text-align: center; background: #e8f5e8; padding: 8px; border-radius: 5px; margin-top: 8px;">
                    <span style="color: #2e7d32; font-weight: bold;">🟢 في الطريق إليك</span>
                </div>
            </div>
        </div>
        """
        
        folium.Marker(
            [driver_location["lat"], driver_location["lng"]],
            tooltip=f"🚗 {driver_name} - {car_type} ({int(driver_distance)}م)",
            popup=folium.Popup(driver_popup, max_width=340),
            icon=Icon(color=car_icon_info["color"], icon=car_icon_info["icon"], prefix=car_icon_info["prefix"])
        ).add_to(trip_map)
        
        # marker الوجهة مع معلومات تفاعلية
        destination_popup = f"""
        <div style="font-family: 'Segoe UI', Arial; font-size: 13px; width: 280px;">
            <div style="background: linear-gradient(135deg, #F44336, #D32F2F); color: white; padding: 12px; margin: -9px -9px 10px -9px; border-radius: 8px 8px 0 0;">
                <h3 style="margin: 0; text-align: center;">🎯 الوجهة</h3>
            </div>
            
            <div style="padding: 8px;">
                <p style="margin: 5px 0;"><strong>📍 الموقع:</strong> نقطة الوصول</p>
                <p style="margin: 5px 0;"><strong>🛣️ المسافة من البداية:</strong> {trip_distance:.1f} كم</p>
                <p style="margin: 5px 0;"><strong>⏱️ وقت الرحلة المتوقع:</strong> {int(trip_distance * 3)} دقيقة</p>
                
                <hr style="margin: 10px 0; border: 1px solid #eee;">
                
                <div style="background: #ffebee; padding: 8px; border-radius: 5px; margin: 8px 0;">
                    <p style="margin: 3px 0; font-size: 12px;"><strong>💰 تفاصيل التكلفة:</strong></p>
                    <p style="margin: 3px 0; font-size: 12px;">🚗 نوع السيارة: {car_type}</p>
                    <p style="margin: 3px 0; font-size: 12px;">💵 التكلفة المتوقعة: {estimated_cost} د.أ</p>
                </div>
                
                <div style="text-align: center; background: #ffcdd2; padding: 6px; border-radius: 5px; margin-top: 8px;">
                    <span style="color: #c62828; font-weight: bold;">🏁 هدف الرحلة</span>
                </div>
            </div>
        </div>
        """
        
        folium.Marker(
            [destination_location["lat"], destination_location["lng"]],
            tooltip=f"🎯 الوجهة - {trip_distance:.1f} كم",
            popup=folium.Popup(destination_popup, max_width=300),
            icon=Icon(color="red", icon="flag-checkered", prefix="fa")
        ).add_to(trip_map)
        
        # رسم المسارات مع تحسين الأداء
        try:
            # مسار السائق للمستخدم
            driver_to_user = gmaps.directions(
                origin=f"{driver_location['lat']},{driver_location['lng']}",
                destination=f"{user_location['lat']},{user_location['lng']}",
                mode="driving",
                language="ar",
                region="jo"
            )
            if driver_to_user:
                points = driver_to_user[0]['overview_polyline']['points']
                coords = polyline.decode(points)
                
                if len(coords) > 1:
                    # المسار الأساسي
                    folium.PolyLine(
                        coords, 
                        color="#FF6600", 
                        weight=4, 
                        opacity=0.8,
                        tooltip="🚗 مسار السائق إليك"
                    ).add_to(trip_map)
                    
                    # التأثير المتحرك المحسن
                    try:
                        plugins.AntPath(
                            coords,
                            color="#FF3300",
                            weight=2,
                            opacity=0.7,
                            dash_array=[10, 5],
                            delay=1000,
                            pulse_color="#FF0000"
                        ).add_to(trip_map)
                    except:
                        pass
                        
        except Exception as e:
            print(f"[تحذير] مسار السائق: {e}")
            folium.PolyLine(
                [[driver_location["lat"], driver_location["lng"]], 
                 [user_location["lat"], user_location["lng"]]],
                color="#FF6600",
                weight=3,
                opacity=0.6,
                tooltip="🚗 مسار السائق (مباشر)"
            ).add_to(trip_map)
        
        # مسار الرحلة الرئيسي
        try:
            user_to_dest = gmaps.directions(
                origin=f"{user_location['lat']},{user_location['lng']}",
                destination=f"{destination_location['lat']},{destination_location['lng']}",
                mode="driving",
                language="ar",
                region="jo"
            )
            if user_to_dest:
                points = user_to_dest[0]['overview_polyline']['points']
                coords = polyline.decode(points)
                
                if len(coords) > 1:
                    folium.PolyLine(
                        coords, 
                        color="#9C27B0", 
                        weight=5, 
                        opacity=0.9,
                        tooltip=f"🛣️ مسار رحلتك - {trip_distance:.1f} كم"
                    ).add_to(trip_map)
                        
        except Exception as e:
            print(f"[تحذير] مسار الرحلة: {e}")
            folium.PolyLine(
                [[user_location["lat"], user_location["lng"]], 
                 [destination_location["lat"], destination_location["lng"]]],
                color="#9C27B0",
                weight=4,
                opacity=0.8,
                tooltip="🛣️ مسار رحلتك (مباشر)"
            ).add_to(trip_map)
        
        # دائرة منطقة الانتظار
        folium.Circle(
            location=[user_location["lat"], user_location["lng"]],
            radius=50,
            color="#2196F3",
            fill=True,
            fillOpacity=0.15,
            tooltip=f"منطقة انتظار {user_name}"
        ).add_to(trip_map)
        
        # إضافة الأدوات بمواضع محسنة لتجنب التداخل
        try:
            # أداة البحث عن الموقع - أعلى اليسار
            plugins.LocateControl(
                auto_start=False, 
                position='topleft',
                drawCircle=True,
                drawMarker=True,
                strings={"title": "تحديد موقعي", "popup": "أنت هنا"}
            ).add_to(trip_map)
            
            # أداة ملء الشاشة - أعلى اليمين
            plugins.Fullscreen(
                position='topright',
                title='ملء الشاشة',
                title_cancel='إلغاء ملء الشاشة'
            ).add_to(trip_map)
            
            # أداة قياس المسافات - أسفل اليسار
            plugins.MeasureControl(
                position='bottomleft',
                primary_length_unit='kilometers',
                secondary_length_unit='meters',
                primary_area_unit='sqkilometers'
            ).add_to(trip_map)
            
            # خريطة مصغرة - أسفل اليمين
            plugins.MiniMap(
                toggle_display=True,
                position='bottomright',
                width=120,
                height=120,
                collapsed_width=25,
                collapsed_height=25
            ).add_to(trip_map)
            
        except Exception as e:
            print(f"[تحذير] أدوات التحكم: {e}")
        
        # تحكم الطبقات - وسط اليمين (منفصل لتجنب التداخل)
        folium.LayerControl(
            position='topright', 
            collapsed=True
        ).add_to(trip_map)
        
        # لوحة معلومات تفاعلية محسنة - أعلى اليسار
        info_panel = f"""
        <div id="info-panel" style="position: fixed; 
                    top: 60px; left: 10px; width: 280px; 
                    background: rgba(255,255,255,0.95); 
                    border: 2px solid #ddd; 
                    border-radius: 12px;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.15);
                    font-family: 'Segoe UI', Arial; 
                    font-size: 13px; 
                    z-index: 1000;
                    backdrop-filter: blur(10px);">
            
            <!-- Header -->
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                        color: white; padding: 12px; 
                        border-radius: 10px 10px 0 0; 
                        text-align: center;">
                <h3 style="margin: 0; font-size: 16px;">🚗 معلومات الرحلة</h3>
            </div>
            
            <!-- Content -->
            <div style="padding: 12px;">
                <!-- Driver Info -->
                <div style="background: #f8f9fa; padding: 8px; border-radius: 6px; margin-bottom: 8px;">
                    <p style="margin: 0; font-weight: bold; color: #333;">👨‍💼 {driver_name}</p>
                    <p style="margin: 2px 0; font-size: 12px;">🚘 {car_type} | ⭐ 4.8/5</p>
                </div>
                
                <!-- Distance & Time -->
                <div style="display: flex; gap: 8px; margin-bottom: 8px;">
                    <div style="flex: 1; background: #e3f2fd; padding: 6px; border-radius: 6px; text-align: center;">
                        <div style="font-size: 18px; font-weight: bold; color: #1976d2;">{int(driver_distance)}م</div>
                        <div style="font-size: 10px; color: #666;">المسافة</div>
                    </div>
                    <div style="flex: 1; background: #e8f5e8; padding: 6px; border-radius: 6px; text-align: center;">
                        <div style="font-size: 18px; font-weight: bold; color: #2e7d32;">{driver_location.get('arrival_time_min', 5)}د</div>
                        <div style="font-size: 10px; color: #666;">الوصول</div>
                    </div>
                </div>
                
                <!-- Trip Details -->
                <div style="background: #fff3e0; padding: 8px; border-radius: 6px; margin-bottom: 8px;">
                    <div style="display:flex; justify-content: space-between; align-items: center;">
                        <span style="font-size: 12px; color: #666;">🛣️ مسافة الرحلة:</span>
                        <span style="font-weight: bold; color: #f57c00;">{trip_distance:.1f} كم</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 4px;">
                        <span style="font-size: 12px; color: #666;">💰 التكلفة المتوقعة:</span>
                        <span style="font-weight: bold; color: #f57c00;">{estimated_cost} د.أ</span>
                    </div>
                </div>
                
                <!-- Weather -->
                <div style="background: #f3e5f5; padding: 8px; border-radius: 6px; margin-bottom: 8px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-size: 12px; color: #666;">🌤️ الطقس الحالي:</span>
                        <span style="font-weight: bold; color: #7b1fa2;">{weather['condition']} {weather['temp']}°C</span>
                    </div>
                </div>
                
                <!-- Status -->
                <div style="text-align: center; background: linear-gradient(135deg, #4caf50, #388e3c); 
                           color: white; padding: 8px; border-radius: 6px; margin-bottom: 8px;">
                    <span style="font-weight: bold; font-size: 12px;">🟢 في الطريق إليك</span>
                </div>
                
                <!-- Current Time -->
                <div style="text-align: center; color: #666; font-size: 11px; margin-top: 4px;">
                    ⏰ آخر تحديث: {current_time.strftime('%H:%M:%S')}
                </div>
            </div>
        </div>
        
        <!-- Toggle Button -->
        <button onclick="toggleInfoPanel()" 
                style="position: fixed; top: 15px; left: 300px; 
                       background: #667eea; color: white; border: none; 
                       border-radius: 50%; width: 35px; height: 35px; 
                       cursor: pointer; z-index: 1001; font-size: 16px;
                       box-shadow: 0 2px 10px rgba(0,0,0,0.2);">
            ◀
        </button>
        
        <script>
        function toggleInfoPanel() {{
            var panel = document.getElementById('info-panel');
            var button = document.querySelector('button[onclick="toggleInfoPanel()"]');
            if (panel.style.display === 'none') {{
                panel.style.display = 'block';
                button.innerHTML = '◀';
                button.style.left = '300px';
            }} else {{
                panel.style.display = 'none';
                button.innerHTML = '▶';
                button.style.left = '10px';
            }}
        }}
        </script>
        """
        
        trip_map.get_root().html.add_child(folium.Element(info_panel))
        
        # دليل الخريطة - أعلى اليمين (تحت تحكم الطبقات)
        legend_html = f"""
        <div style="position: fixed; 
                    top: 120px; right: 10px; width: 200px; 
                    background: rgba(255,255,255,0.95); 
                    border: 2px solid #ddd; 
                    border-radius: 12px;
                    box-shadow: 0 4px 15px rgba(0,0,0,0.1);
                    font-family: 'Segoe UI', Arial; 
                    font-size: 12px; 
                    z-index: 1000;
                    backdrop-filter: blur(5px);">
            
            <div style="background: linear-gradient(135deg, #ff6b6b, #ee5a24); 
                        color: white; padding: 10px; 
                        border-radius: 10px 10px 0 0; 
                        text-align: center;">
                <h4 style="margin: 0; font-size: 14px;">🗺️ دليل الخريطة</h4>
            </div>
            
            <div style="padding: 10px;">
                <div style="display: flex; align-items: center; margin: 6px 0;">
                    <i class="fa fa-user" style="color: #2196F3; width: 16px; font-size: 14px;"></i>
                    <span style="margin-left: 8px; font-size: 11px;">{user_name}</span>
                </div>
                
                <div style="display: flex; align-items: center; margin: 6px 0;">
                    <i class="fa fa-{car_icon_info['icon']}" style="color: {car_icon_info['color']}; width: 16px; font-size: 14px;"></i>
                    <span style="margin-left: 8px; font-size: 11px;">{driver_name} ({car_type})</span>
                </div>
                
                <div style="display: flex; align-items: center; margin: 6px 0;">
                    <i class="fa fa-flag-checkered" style="color: #F44336; width: 16px; font-size: 14px;"></i>
                    <span style="margin-left: 8px; font-size: 11px;">الوجهة</span>
                </div>
                
                <hr style="margin: 8px 0; border: 1px solid #eee;">
                
                <div style="margin: 4px 0;">
                    <span style="color: #FF6600; font-weight: bold;">━━━</span>
                    <span style="font-size: 10px; margin-left: 4px;">مسار السائق</span>
                </div>
                
                <div style="margin: 4px 0;">
                    <span style="color: #9C27B0; font-weight: bold;">━━━</span>
                    <span style="font-size: 10px; margin-left: 4px;">مسار الرحلة</span>
                </div>
                
                <div style="margin: 4px 0;">
                    <span style="color: #2196F3; font-size: 14px;">●</span>
                    <span style="font-size: 10px; margin-left: 4px;">منطقة الانتظار</span>
                </div>
            </div>
        </div>
        """
        
        trip_map.get_root().html.add_child(folium.Element(legend_html))
        
        # إضافة إشعار تفاعلي للحالة - أسفل الوسط
        status_notification = f"""
        <div style="position: fixed; 
                    bottom: 20px; left: 50%; transform: translateX(-50%); 
                    background: rgba(76, 175, 80, 0.95); 
                    color: white; 
                    padding: 12px 20px; 
                    border-radius: 25px;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.2);
                    font-family: 'Segoe UI', Arial; 
                    font-size: 14px; 
                    z-index: 1000;
                    backdrop-filter: blur(10px);
                    animation: pulse 2s infinite;">
            
            <div style="display: flex; align-items: center; gap: 8px;">
                <div style="width: 10px; height: 10px; background: #fff; border-radius: 50%; 
                           animation: blink 1s infinite;"></div>
                <span style="font-weight: bold;">
                    🚗 {driver_name} في الطريق - سيصل خلال {driver_location.get('arrival_time_min', 5)} دقائق
                </span>
            </div>
        </div>
        
        <style>
        @keyframes pulse {{
            0% {{ transform: translateX(-50%) scale(1); }}
            50% {{ transform: translateX(-50%) scale(1.02); }}
            100% {{ transform: translateX(-50%) scale(1); }}
        }}
        
        @keyframes blink {{
            0%, 50% {{ opacity: 1; }}
            51%, 100% {{ opacity: 0.3; }}
        }}
        </style>
        """
        
        trip_map.get_root().html.add_child(folium.Element(status_notification))
        
        # إضافة أيقونات Font Awesome
        fontawesome_css = """
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/4.7.0/css/font-awesome.min.css">
        """
        trip_map.get_root().html.add_child(folium.Element(fontawesome_css))
        
        # تحسين الأداء مع إضافة meta tags
        performance_meta = """
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <meta name="description" content="JeenyAgent - Smart Transportation Mapping">
        <style>
        body {
            margin: 0;
            padding: 0;
            font-family: 'Segoe UI', Arial, sans-serif;
        }
        .leaflet-container {
            font-family: 'Segoe UI', Arial, sans-serif;
        }
        .leaflet-popup-content {
            margin: 0 !important;
        }
        .leaflet-popup-content-wrapper {
            border-radius: 8px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.15);
        }
        </style>
        """
        trip_map.get_root().html.add_child(folium.Element(performance_meta))
        
        # حفظ الخريطة
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"enhanced_trip_map_{timestamp}.html"
        
        maps_dir = "maps"
        if not os.path.exists(maps_dir):
            print(f"إنشاء مجلد الخرائط: {maps_dir}")
            os.makedirs(maps_dir)
        
        filepath = os.path.join(maps_dir, filename)
        abs_filepath = os.path.abspath(filepath)
        
        print(f"حفظ الخريطة المحسنة في: {abs_filepath}")
        try:
            trip_map.save(filepath)
            print(f"✅ تم حفظ الخريطة المحسنة بنجاح في: {abs_filepath}")
            
            # التحقق من وجود الملف
            if os.path.exists(filepath):
                file_size = os.path.getsize(filepath)
                print(f"📊 حجم الملف: {file_size} بايت")
                
                if file_size > 1000:
                    print("🔍 الملف تم حفظه بنجاح ويحتوي على بيانات")
                    
                    # فتح الخريطة تلقائياً
                    print("🚀 محاولة فتح الخريطة المحسنة في المتصفح...")
                    if open_file_in_browser(filepath):
                        print("✅ تم فتح الخريطة المحسنة في المتصفح بنجاح!")
                        print(f"🎯 الخريطة تحتوي على:")
                        print(f"   - معلومات تفاعلية شاملة")
                        print(f"   - {len([layer for layer in trip_map._children.values() if hasattr(layer, 'tile_name')])} أنواع خرائط")
                        print(f"   - أدوات تحكم محسنة ومنظمة")
                        print(f"   - إشعارات حية للحالة")
                        print(f"   - تصميم احترافي ومتجاوب")
                    else:
                        print("⚠️ لم يتم فتح المتصفح تلقائياً، يمكنك فتح الملف يدوياً:")
                        print(f"   الملف موجود في: {abs_filepath}")
                else:
                    print("⚠️ الملف تم إنشاؤه لكنه صغير جداً")
            else:
                print("❌ فشل في حفظ الملف!")
                return None
                
        except Exception as e:
            print(f"❌ خطأ في حفظ الخريطة المحسنة: {e}")
            return None
        
        return filename
        
    except Exception as e:
        print(f"❌ خطأ عام في إنشاء الخريطة المحسنة: {e}")
        import traceback
        traceback.print_exc()
        return None

def create_trip_summary(user_location, driver_location, destination_location, user_name="الراكب", driver_name="السائق"):
    """إنشاء ملخص تفاعلي للرحلة"""
    try:
        car_type = driver_location.get('car_type', 'عادية')
        
        # حساب المسافات
        driver_distance = calculate_distance_km(
            user_location["lat"], user_location["lng"],
            driver_location["lat"], driver_location["lng"]
        ) * 1000
        
        trip_distance = calculate_distance_km(
            user_location["lat"], user_location["lng"],
            destination_location["lat"], destination_location["lng"]
        )
        
        estimated_cost = estimate_trip_cost(trip_distance, car_type)
        weather = get_weather_info()
        
        current_time = datetime.now()
        arrival_time = current_time + timedelta(minutes=driver_location.get('arrival_time_min', 5))
        
        summary = {
            "trip_info": {
                "user_name": user_name,
                "driver_name": driver_name,
                "car_type": car_type,
                "current_time": current_time.strftime('%H:%M:%S'),
                "arrival_time": arrival_time.strftime('%H:%M')
            },
            "distances": {
                "driver_to_user_m": int(driver_distance),
                "trip_distance_km": round(trip_distance, 1),
                "estimated_time_min": int(trip_distance * 3)
            },
            "costs": {
                "estimated_cost_jod": estimated_cost,
                "currency": "د.أ"
            },
            "weather": weather,
            "status": "driver_on_way"
        }
        
        print("📋 ملخص الرحلة:")
        print(f"   🚗 السائق: {driver_name} ({car_type})")
        print(f"   📏 المسافة للسائق: {int(driver_distance)} متر")
        print(f"   🛣️ مسافة الرحلة: {trip_distance:.1f} كم")
        print(f"   💰 التكلفة المتوقعة: {estimated_cost} د.أ")
        print(f"   🌤️ الطقس: {weather['condition']} ({weather['temp']}°C)")
        print(f"   ⏰ وقت الوصول المتوقع: {arrival_time.strftime('%H:%M')}")
        
        return summary
        
    except Exception as e:
        print(f"❌ خطأ في إنشاء ملخص الرحلة: {e}")
        return None

# مثال على الاستخدام
if __name__ == "__main__":
    # إعداد مواقع تجريبية (عمان، الأردن)
    sample_user_location = {"lat": 31.9566, "lng": 35.9457}  # عمان
    sample_destination = {"lat": 31.9539, "lng": 35.9106}    # وسط البلد
    sample_driver = {
        "lat": 31.9580, 
        "lng": 35.9400,
        "car_type": "عائلية",
        "distance_m": 800,
        "arrival_time_min": 4
    }
    
    print("🚀 بدء إنشاء خريطة محسنة تجريبية...")
    
    # إنشاء ملخص الرحلة
    summary = create_trip_summary(
        sample_user_location, 
        sample_driver, 
        sample_destination,
        "أحمد محمد",
        "محمد علي"
    )
    
    # إنشاء الخريطة
    result = create_trip_map(
        sample_user_location, 
        sample_driver, 
        sample_destination,
        "أحمد محمد",
        "محمد علي"
    )
    
    if result:
        print(f"🎉 تم إنشاء الخريطة المحسنة بنجاح: {result}")
    else:
        print("❌ فشل في إنشاء الخريطة المحسنة")