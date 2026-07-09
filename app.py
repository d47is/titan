from flask import Flask, render_template, request, jsonify, send_file
import requests
import datetime
import webbrowser
import random
import base64
import io
import speech_recognition as sr
from pydub import AudioSegment
import tempfile
import os
import time
import json

app = Flask(__name__)

OPENROUTER_API_KEY = "__"

conversation_history = []
MAX_HISTORY = 20

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        if not data:
            return jsonify({'response': 'No data received', 'type': 'error'})
        
        user_message = data.get('message', '')
        if not user_message:
            return jsonify({'response': 'Please say or type something.', 'type': 'error'})
        
        if handle_system_command(user_message):
            response_text = get_system_response(user_message)
            return jsonify({
                'response': response_text or 'Command executed.',
                'type': 'system'
            })
        
        response_text = get_ai_response(user_message)
        return jsonify({
            'response': response_text or 'No response from AI.',
            'type': 'ai'
        })
    
    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({
            'response': f'Server error: {str(e)}',
            'type': 'error'
        })

@app.route('/speak', methods=['POST'])
def speak():
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No data received'}), 400
        
        text = data.get('text', '')
        if not text:
            return jsonify({'error': 'No text provided'}), 400
        
        # Try Google TTS first
        try:
            audio_content = get_google_tts(text)
            if audio_content:
                return send_file(
                    io.BytesIO(audio_content),
                    mimetype='audio/mpeg',
                    as_attachment=True,
                    download_name='response.mp3'
                )
        except Exception as e:
            print(f"Google TTS failed: {e}")
        
        # Fallback to pyttsx3
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty('rate', 170)
            engine.setProperty('volume', 0.9)
            
            with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_file:
                temp_path = temp_file.name
            
            engine.save_to_file(text, temp_path)
            engine.runAndWait()
            engine.stop()
            
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 1000:
                return send_file(
                    temp_path,
                    mimetype='audio/wav',
                    as_attachment=True,
                    download_name='response.wav'
                )
        except Exception as e:
            print(f"pyttsx3 failed: {e}")
        
        return jsonify({'error': 'All TTS methods failed'}), 500
    
    except Exception as e:
        print(f"Speak error: {e}")
        return jsonify({'error': str(e)}), 500

def get_google_tts(text):
    """Generate TTS using Google Translate TTS (free, no API key)"""
    try:
        # Google TTS endpoint
        url = "https://translate.google.com/translate_tts"
        params = {
            'ie': 'UTF-8',
            'q': text,
            'tl': 'en',
            'client': 'tw-ob',
            'textlen': len(text)
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=10)
        
        if response.status_code == 200 and len(response.content) > 1000:
            return response.content
        return None
    except Exception as e:
        print(f"Google TTS error: {e}")
        return None

@app.route('/speech-to-text', methods=['POST'])
def speech_to_text():
    try:
        data = request.json
        if not data:
            return jsonify({'text': '', 'error': 'No data received'})
        
        base64_audio = data.get('audio', '')
        if not base64_audio:
            return jsonify({'text': '', 'error': 'No audio data received'})
        
        try:
            audio_bytes = base64.b64decode(base64_audio)
        except Exception as e:
            return jsonify({'text': '', 'error': f'Invalid audio data: {str(e)}'})
        
        try:
            audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="webm")
            audio = audio.set_frame_rate(16000).set_channels(1)
            
            wav_bytes = io.BytesIO()
            audio.export(wav_bytes, format="wav")
            wav_bytes.seek(0)
            
            recognizer = sr.Recognizer()
            with sr.AudioFile(wav_bytes) as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio_data = recognizer.record(source)
                
                try:
                    text = recognizer.recognize_google(audio_data, language="en-US")
                    if text and text.strip():
                        return jsonify({'text': text.strip()})
                    else:
                        return jsonify({'text': ''})
                except sr.UnknownValueError:
                    return jsonify({'text': ''})
                except sr.RequestError as e:
                    print(f"Google STT error: {e}")
                    return jsonify({'text': ''})
                    
        except Exception as e:
            print(f"Audio processing error: {e}")
            return jsonify({'text': '', 'error': str(e)})
            
    except Exception as e:
        print(f"Speech-to-text error: {e}")
        return jsonify({'text': '', 'error': str(e)})

def get_ai_response(query):
    try:
        context = ""
        for msg in conversation_history[-10:]:
            role = "User" if msg["role"] == "user" else "Assistant"
            context += f"{role}: {msg['content']}\n"
        
        system_prompt = """You are TITAN, a professional AI assistant. Follow these rules strictly:

1. Never provide reasoning, step-by-step thinking, or explanations
2. Always give only the final, direct answer
3. Keep responses concise and professional (maximum 20 words)
4. Use clear, formal English
5. If asked for code, output only the code without explanation
6. If asked a question, answer directly without any preface

Never explain your process. Always respond with the final answer only."""

        payload = {
            "model": "qwen/qwen3-32b",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ],
            "max_tokens": 150,
            "temperature": 0.7
        }

        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:5000",
            },
            json=payload,
            timeout=15
        )

        if response.status_code == 200:
            result = response.json()
            if result and "choices" in result and len(result["choices"]) > 0:
                ai_response = result["choices"][0]["message"]["content"]
                if ai_response and ai_response.strip():
                    conversation_history.append({"role": "user", "content": query})
                    conversation_history.append({"role": "assistant", "content": ai_response})
                    
                    if len(conversation_history) > MAX_HISTORY:
                        conversation_history.pop(0)
                        conversation_history.pop(0)
                    
                    return ai_response.strip()
                else:
                    return "I apologize, but I couldn't generate a response. Please try again."
            else:
                return "Invalid response format from API."
        else:
            error_msg = response.json().get('error', {}).get('message', str(response.status_code))
            print(f"API Error: {error_msg}")
            return f"API Error: {error_msg}"

    except requests.exceptions.Timeout:
        return "Request timed out. Please try again."
    except requests.exceptions.ConnectionError:
        return "Connection error. Please check your internet connection."
    except Exception as e:
        print(f"AI response error: {e}")
        return f"Error: {str(e)}"

def handle_system_command(query):
    query_lower = query.lower()
    system_commands = [
        'open youtube', 'open google', 'open github', 'open reddit',
        'time', 'date', 'joke', 'clear', 'help'
    ]
    return any(cmd in query_lower for cmd in system_commands)

def get_system_response(query):
    query_lower = query.lower()

    if 'open youtube' in query_lower:
        webbrowser.open("https://youtube.com")
        return "Opening YouTube"

    elif 'open google' in query_lower:
        webbrowser.open("https://google.com")
        return "Opening Google"

    elif 'open github' in query_lower:
        webbrowser.open("https://github.com")
        return "Opening GitHub"

    elif 'open reddit' in query_lower:
        webbrowser.open("https://reddit.com")
        return "Opening Reddit"

    elif 'time' in query_lower:
        now = datetime.datetime.now().strftime("%I:%M %p")
        return f"The time is {now}"

    elif 'date' in query_lower:
        now = datetime.datetime.now().strftime("%B %d, %Y")
        return f"Today is {now}"

    elif 'joke' in query_lower:
        jokes = [
            "Why do programmers prefer dark mode? Light attracts bugs.",
            "What do you call a fake noodle? An impasta.",
            "Why did the scarecrow win an award? Outstanding in his field.",
            "What do you call a bear with no teeth? A gummy bear."
        ]
        return random.choice(jokes)

    elif 'help' in query_lower:
        return "Commands: open youtube, open google, open github, open reddit, time, date, joke, clear, help"

    elif 'clear' in query_lower:
        conversation_history.clear()
        return "Chat cleared"

    return "Command executed."

if __name__ == '__main__':
    print("=" * 50)
    print("JARVIS AI - Professional Assistant")
    print("=" * 50)
    print("Open http://localhost:5000 in your browser")
    print("=" * 50)

    if OPENROUTER_API_KEY == "YOUR_OPENROUTER_API_KEY_HERE":
        print("WARNING: Set your OpenRouter API key in app.py!")
        print("Get key: https://openrouter.ai/keys")

    app.run(debug=True, host='0.0.0.0', port=5000)