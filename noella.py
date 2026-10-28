import os
import telebot
import base64
import io
import threading 
import time
from pypdf import PdfReader
from openai import OpenAI
from flask import Flask
from threading import Thread

# ==========================================
# KEYS ARE PULLED FROM RENDER'S ENVIRONMENT
# (For local testing, you can temporarily put them in the quotes)
# ==========================================
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', 'PASTE_LOCAL_TOKEN_HERE')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', 'PASTE_LOCAL_KEY_HERE')

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=GROQ_API_KEY)

# --- HELPER: Split long messages ---
def split_long_message(text, max_length=4000):
    if len(text) <= max_length:
        return [text]
    chunks = []
    while len(text) > max_length:
        split_index = text.rfind('\n', 0, max_length)
        if split_index == -1:
            split_index = text.rfind('. ', 0, max_length)
        if split_index == -1:
            split_index = max_length
        chunks.append(text[:split_index].strip())
        text = text[split_index:].strip()
    if text:
        chunks.append(text)
    return chunks

# --- START COMMAND ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Hello! I am Noella. I can chat, read images, read PDFs, and set timers!\n\nTry typing: /timer 10")

# --- TIMER COMMAND (Cloud Version - Sends a Telegram Alert) ---
@bot.message_handler(commands=['timer'])
def set_timer(message):
    try:
        command_parts = message.text.split()
        if len(command_parts) < 2:
            bot.reply_to(message, "Please tell me how many seconds to set. Example: /timer 30")
            return
        
        seconds = int(command_parts[1])
        bot.reply_to(message, f"⏱️ Timer set for {seconds} seconds! I will alert you when it's done.")
        
        def timer_task():
            time.sleep(seconds) 
            
            # Send an alert message to your phone
            alert_text = f"🚨 **DING! DING! DING!** 🚨\n\nYour {seconds}-second timer is done!"
            bot.send_message(message.chat.id, alert_text, parse_mode='Markdown')
            
        t = threading.Thread(target=timer_task)
        t.start()

    except ValueError:
        bot.reply_to(message, "Please send a valid number. Example: /timer 30")
    except Exception as e:
        bot.reply_to(message, f"Error setting timer: {e}")

# --- 1. HANDLE TEXT MESSAGES ---
@bot.message_handler(func=lambda message: True)
def chat_with_ai(message):
    bot.send_chat_action(message.chat.id, 'typing')
    try:
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[
                {"role": "system", "content": "You are Noella, a helpful and friendly assistant."},
                {"role": "user", "content": message.text}
            ]
        )
        reply_text = response.choices[0].message.content
        for chunk in split_long_message(reply_text):
            bot.reply_to(message, chunk)
    except Exception as e:
        bot.reply_to(message, f"Oops, my AI brain had an error: {e}")

# --- 2. HANDLE IMAGES ---
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    bot.send_chat_action(message.chat.id, 'typing')
    try:
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        base64_image = base64.b64encode(downloaded_file).decode('utf-8')

        response = client.chat.completions.create(
            model="qwen/qwen3.8-27b",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image in detail."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ]
        )
        reply_text = response.choices[0].message.content
        for chunk in split_long_message(reply_text):
            bot.reply_to(message, chunk)
    except Exception as e:
        bot.reply_to(message, f"Oops, I couldn't read that image: {e}")

# --- 3. HANDLE PDF DOCUMENTS ---
@bot.message_handler(content_types=['document'])
def handle_document(message):
    if not message.document.file_name.lower().endswith('.pdf'):
        bot.reply_to(message, "Sorry, I can only read PDF files right now.")
        return

    bot.send_chat_action(message.chat.id, 'typing')
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        reader = PdfReader(io.BytesIO(downloaded_file))
        extracted_text = ""
        for page in reader.pages:
            text = page.extract_text()
            if text:
                extracted_text += text + "\n"

        if not extracted_text.strip():
            bot.reply_to(message, "I downloaded the PDF, but couldn't extract any text. It might be a scanned image.")
            return

        bot.reply_to(message, "I've read the PDF, let me analyze it...")
        prompt_text = extracted_text[:8000] 
        
        response = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[
                {"role": "system", "content": "You are Noella. Summarize or answer questions based on the provided document text."},
                {"role": "user", "content": f"Here is the document content:\n\n{prompt_text}\n\nPlease summarize this."}
            ]
        )
        reply_text = response.choices[0].message.content
        for chunk in split_long_message(reply_text):
            bot.reply_to(message, chunk)

    except Exception as e:
        bot.reply_to(message, f"Oops, error reading PDF: {e}")

# --- WEB SERVER (For Render 24/7 hosting) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Noella is alive and running!"

def run_bot():
    print("Starting Telegram bot...")
    bot.infinity_polling()

if __name__ == "__main__":
    t = Thread(target=run_bot)
    t.start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)