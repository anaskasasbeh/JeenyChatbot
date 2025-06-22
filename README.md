# 🚗 JeenyChatbot

JeenyChatbot is an intelligent, fully interactive transportation assistant designed specifically for Arabic speakers in Jordan. Built using cutting-edge technologies such as LangChain, OpenAI GPT-4-mini, and Gradio, this application provides a smart, seamless, and engaging user experience similar to popular ride-hailing services like Uber, Careem, and Jeeny.

## 🌟 Key Features

### 🗣️ Intelligent Chatbot Interaction

* **Natural Language Processing (NLP)** powered by OpenAI's GPT-4-mini.
* Understands and processes user input in Jordanian Arabic dialect.
* Capable of dynamic conversational interactions, asking clarifying questions when necessary.

### ⚙️ Agentic AI

* Leverages LangChain to intelligently select and switch between tools based on context.
* Automatically manages ride details, location parsing, and car type selection.

### 🎤 Multi-modal Input/Output

* Supports both text and voice interactions.
* Advanced speech recognition and Text-to-Speech (TTS) capabilities optimized for Arabic.
* Provides real-time voice interaction for enhanced accessibility.

### 🧠 Memory Management

* Persistent conversational memory retains essential details throughout the interaction.
* Stores information such as vehicle preferences, current location, and destination.

### 📍 Saved Locations Feature

JeenyChatbot supports personalized saved locations that users can refer to using natural names. These locations are stored in the `saved_locations.json` file and are parsed intelligently by the agent during conversation.

For example, you can say:

- "خذني على الجامعة"
- "غير الموقع لـ الدار"
- "وصلني على الحديقة"

Example saved locations:
```json
{
  "الدار": "[removed]",
  "دار جدي": "[removed]",
  "الجامعة": "جامعة اليرموك،",
  "المستشفى": "مستشفى الملك المؤسس عبد الله الجامعي"
}
```

### 🗺️ Interactive Maps & Dynamic Routing

* Utilizes Google Maps APIs to generate detailed trip summaries, route planning, and driver tracking.
* Interactive maps are dynamically generated using Folium, displaying trip details clearly.

### 🚘 Car Type Customization

* Allows users to choose from multiple vehicle types:

  * **Regular (عادية)**
  * **Taxi (تاكسي)**
  * **Family-sized (عائلية)**
  * **VIP (فاخرة)**
* Pricing dynamically adjusts based on vehicle choice.

### 🔄 Flexible Trip Modifications

* Enables users to modify trip details, including changing the vehicle type, start location, or destination seamlessly.
* Real-time recalculation of trip costs and timings.

### 💻 User-Friendly Interface

* Elegant, responsive, and intuitive user interface powered by Gradio.
* Easy-to-use interface with clear interaction design for broader audience accessibility.

## 📂 Project Structure

```markdown
JeenyChatbot/
├── backend/
│   ├── tools/
│   │   ├── car_type_selector_tool.py
│   │   ├── change_car_type_tool.py
│   │   ├── get_directions_tool.py
│   │   └── modify_location_tool.py
│   ├── jeeny_agent/
│   │   ├── driver.py
│   │   ├── geocoding.py
│   │   ├── mapping.py
│   │   ├── models.py
│   │   ├── nlu.py
│   │   └── routing.py
│   ├── utils/
│   │   └── voice.py
│   ├── main.py
│   └── saved_locations.json
│
├── frontend/
│   └── gradio_app.py
│
├── maps/ (generated maps)
│
├── requirements.txt
├── .env.example
└── README.md
```

## 🛠️ Technologies Used

* **LangChain**: For dynamic agent interactions and intelligent tool-switching.
* **OpenAI GPT-4o**: Advanced NLP capabilities to understand Arabic dialect.
* **Google Maps APIs**: Directions, Geocoding, and Road APIs for accurate navigation and mapping.
* **Gradio**: For intuitive, interactive web-based interface.
* **Folium**: To create interactive maps displaying route details.
* **SpeechRecognition, gTTS, pyttsx3**: For robust speech-to-text and text-to-speech functionalities.
* **FastAPI & Uvicorn**: Future-ready backend structure (optional server deployment).

## 🚀 Installation and Setup

### Clone the Repository

```bash
git clone https://github.com/your_username/JeenyChatbot.git
cd JeenyChatbot
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Configure Environment Variables

* Rename `.env.example` to `.env` and replace with your actual API keys:

```env
OPENAI_API_KEY=your_openai_api_key
GOOGLE_API_KEY=your_google_api_key
```

### Run the Application

To launch the Gradio-based user interface:

```bash
python frontend/gradio_app.py
```

To run via CLI with optional voice commands:

```bash
python backend/main.py --use-voice
```

## 🧑‍💻 Usage Examples

* "بدي أروح من إربد إلى عمان"
* "غير نوع السيارة لـ VIP"
* "بدي أعدل الرحلة لتصير من الزرقاء إلى السلط"
* "غير الوجهة للجامعة الأردنية"

## 🌐 Contribution

Contributions are welcome! Please fork the repository, create your branch, commit your changes, and open a pull request.

## 📜 License

This project is licensed under the MIT License. See the [MIT LICENSE](https://github.com/anaskasasbeh28/JeenyChatbot/blob/main/LICENSE) file for details.


---

✨ **Happy coding!** Feel free to reach out or raise issues for feedback, questions, or feature requests! 🚗💨🎉

---

> Made with ❤️ and a lot of Tea by **Anas & Cloude** ☁️

