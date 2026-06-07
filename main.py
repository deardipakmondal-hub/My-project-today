import telebot
from telebot import types
import time
from datetime import datetime
import pytz
import schedule
import threading
import firebase_admin
from firebase_admin import credentials, db
import os
import json

# --- CONFIGURATION ---
API_TOKEN = '8675792162:AAECQMno0-Rdk4QM7z0tAqe410fcYtj0Sqw'
ADMIN_GROUP_ID = -1003758213595
KOLKATA = pytz.timezone('Asia/Kolkata')
# Fix: URL small case 'https'
FIREBASE_DB_URL = 'https://fullmap-903ce-default-rtdb.asia-southeast1.firebasedatabase.app/'

# --- FIREBASE INITIALIZE ---
if 'FIREBASE_CREDENTIALS' in os.environ:
    cred_data = json.loads(os.environ['FIREBASE_CREDENTIALS'])
    cred = credentials.Certificate(cred_data)
else:
    # Local testing ke liye backup (agar JSON file ho)
    cred = credentials.Certificate("serviceAccountKey.json")

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': FIREBASE_DB_URL
    })

bot = telebot.TeleBot(API_TOKEN)
bot.remove_webhook()

# --- DATA STORAGE ---
topic_map, player_to_topic, topic_data = {}, {}, {}
active_sessions, admin_activity, button_lock_tracker = set(), {}, {}
player_complaint_counts, player_locks, blocked_players = {}, {}, set()
player_permanent_topic, status_message_id = {}, None

KEYWORDS = ["room full", "fullmap", "room kick", "room id", "rom", "kick", "room", "kik", "id", "full", "entry", "problem", "coin"]

# --- HELPER FUNCTIONS ---
def is_working_hours():
    now = datetime.now(KOLKATA).time()
    return datetime.strptime("08:00", "%H:%M").time() <= now <= datetime.strptime("23:00", "%H:%M").time()

def get_circle_num(n):
    circles = {1:"❶", 2:"❷", 3:"❸", 4:"❹", 5:"❺", 6:"❻", 7:"❼", 8:"❽", 9:"❾", 10:"❿"}
    return circles.get(n, f"({n})")

def get_action_markup(t_id):
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("❓ POV", callback_data=f"ask_pov_{t_id}"),
        types.InlineKeyboardButton("🌺 Solve", callback_data=f"solve_{t_id}"),
        types.InlineKeyboardButton("❌ Reject", callback_data=f"reject_{t_id}")
    )
    return markup

# --- BACKGROUND WORKER ---
def firebase_queue_worker():
    print("🚀 Background Queue Worker Active...")
    queue_ref = db.reference('complaint_queue')
    while True:
        try:
            complaints = queue_ref.get()
            if complaints:
                for key, data in complaints.items():
                    # Logic implementation for complaint handling
                    # ... (Aapka original logic yahan rahega)
                    queue_ref.child(key).delete()
        except Exception as e:
            print(f"Error: {e}")
        time.sleep(3)

threading.Thread(target=firebase_queue_worker, daemon=True).start()

# --- HANDLERS ---
@bot.message_handler(func=lambda message: message.chat.type == 'private')
def handle_player_messages(message):
    # Player interaction logic
    pass

@bot.callback_query_handler(func=lambda call: True)
def handle_admin_action(call):
    # Admin buttons logic
    pass

# --- START BOT ---
if __name__ == "__main__":
    print("✅ Bot is running...")
    bot.infinity_polling()
