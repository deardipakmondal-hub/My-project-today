import telebot
from telebot import types
import time
from datetime import datetime
import pytz 
import schedule
import threading
import firebase_admin
from firebase_admin import credentials, db

# --- CONFIGURATION ---
API_TOKEN = '8675792162:AAECQMno0-Rdk4QM7z0tAqe410fcYtj0Sqw'
ADMIN_GROUP_ID = -1003758213595
KOLKATA = pytz.timezone('Asia/Kolkata')
# 🔥 Aapka Singapore region wala Firebase URL yahan bilkul sahi format mein set hai:
FIREBASE_DB_URL = 'Https://fullmap-903ce-default-rtdb.asia-southeast1.firebasedatabase.app/'

# --- FIREBASE INITIALIZE ---
cred = credentials.Certificate("credentials.json")
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': FIREBASE_DB_URL
    })

bot = telebot.TeleBot(API_TOKEN)
bot.remove_webhook() 

# --- DATA STORAGE ---
topic_map = {} 
player_to_topic = {} 
topic_data = {} 
active_sessions = set()
admin_activity = {}   
status_message_id = None 
button_lock_tracker = {}
player_complaint_counts = {} 
player_locks = {}
blocked_players = set() 
player_permanent_topic = {}

KEYWORDS = ["room full", "fullmap", "fullmap solo", "room kick", "room id", "rom", "kick", "room", "kik", "id", "full", "entry", "full map", "fullmap problem", "rule break", "rule", "break", "use", "gun", "hight", "paisa", "money", "coin", "problem", "1 kill", "2 kill", "3 kill", "4 kill", "5 kill", "6 kill", "7 kill", "8 kill", "9 kill", "10 kill", "11 kill", "12 kill", "13 kill", "14 kill", "15 kill", "16 kill", "17 kill"]

# --- HELPERS ---
def is_working_hours():
    """Checks if current IST time is between 8 AM and 11 PM"""
    now = datetime.now(KOLKATA).time()
    start = datetime.strptime("08:00", "%H:%M").time()
    end = datetime.strptime("23:00", "%H:%M").time()
    return start <= now <= end

def get_circle_num(n):
    circles = {1:"❶", 2:"❷", 3:"❸", 4:"❹", 5:"❺", 6:"❻", 7:"❼", 8:"❽", 9:"❾", 10:"❿"}
    return circles.get(n, f"({n})")

def format_duration(seconds):
    if seconds < 0: seconds = 0
    mins, secs = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    if hours > 0: return f"{hours}h {mins}m"
    if mins > 0: return f"{mins}m {secs}s"
    return f"{secs}s"

def check_permission(user_id, chat_id):
    try:
        status = bot.get_chat_member(chat_id, user_id).status
        if status == 'creator': return 'owner'
        if status == 'administrator': return 'admin'
        return 'member'
    except: return 'member'

def get_action_markup(t_id):
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.add(
        types.InlineKeyboardButton("❓ POV", callback_data=f"ask_pov_{t_id}"),
        types.InlineKeyboardButton("🌺 Solve", callback_data=f"solve_{t_id}"),
        types.InlineKeyboardButton("❌ Reject", callback_data=f"reject_{t_id}")
    )
    return markup

# --- DASHBOARD ---
def update_admin_dashboard(chat_id, thread_id=1):
    global status_message_id
    text = "📊 **ADMIN LIVE PERFORMANCE BAR**\n━━━━━━━━━━━━━━━━━━━━\n"
    if not admin_activity:
        text += "⏳ *Waiting for actions...*\n"
    else:
        current_time = time.time()
        for a_id, data in admin_activity.items():
            time_since_last_action = current_time - data['last_seen']
            status = "🟢 Online" if time_since_last_action < 300 else "⚪ Offline"
            
            if is_working_hours():
                if time_since_last_action < 300:
                    data['total_online_time'] += (current_time - data['last_update_tick'])
                else:
                    data['total_offline_time'] += (current_time - data['last_update_tick'])
            
            data['last_update_tick'] = current_time
            text += (f"👤 **{data['name']}** | {status}\n"
                     f"┣ ⏳ Work: `{format_duration(data['total_online_time'])}` \n"
                     f"┣ 💤 Rest: `{format_duration(data['total_offline_time'])}` \n"
                     f"┣ 🌺 `{data['solved']}` | ❌ `{data['rejected']}` | ❓ `{data['pov_asked']}` | 💬 `{data['manual_chat']}`\n"
                     f"━━━━━━━━━━━━━━━━━━━━\n")
    
    now_kolkata = datetime.now(KOLKATA)
    text += f"🕒 Last Sync: {now_kolkata.strftime('%I:%M:%S %p')} (IST)\n📅 Date: `{now_kolkata.strftime('%A | %B %d | %Y')}`"
    
    if not is_working_hours():
        text += "\n\n⚠️ **Duty Off: Stats counting paused.**"

    try:
        if status_message_id:
            bot.edit_message_text(text, chat_id, status_message_id, parse_mode="Markdown")
        else:
            msg = bot.send_message(chat_id, text, message_thread_id=thread_id, parse_mode="Markdown")
            status_message_id = msg.message_id
            bot.pin_chat_message(chat_id, status_message_id)
    except: pass

def init_admin(admin_id, name):
    if admin_id not in admin_activity:
        current = time.time()
        admin_activity[admin_id] = {
            'name': name, 'solved': 0, 'rejected': 0, 'pov_asked': 0, 'manual_chat': 0,
            'last_seen': current, 'last_update_tick': current,
            'total_online_time': 0, 'total_offline_time': 0
        }

# --- AUTOMATION THREAD ---
def scheduler_loop():
    schedule.every().day.at("23:00").do(update_admin_dashboard, chat_id=ADMIN_GROUP_ID)
    while True:
        schedule.run_pending()
        time.sleep(60)

threading.Thread(target=scheduler_loop, daemon=True).start()

# --- BACKGROUND FIREBASE WORKER (Bulletproof Rate Limiter) ---
def firebase_queue_worker():
    """Yeh thread background me automatic chalega aur rate limit handle karega"""
    global topic_map, player_to_topic, topic_data, player_permanent_topic
    print("🚀 Background Queue Worker Active! Ready for heavy traffic...")
    queue_ref = db.reference('complaint_queue')
    
    while True:
        try:
            complaints = queue_ref.get()
            if complaints:
                for key, data in complaints.items():
                    p_id = data['p_id']
                    ign = data['ign']
                    issue = data['issue']
                    reg_no = data['reg_no']
                    count_tag = data['count_tag']
                    file_id = data['file_id']
                    
                    perm_ref = db.reference(f'player_permanent_topic/{p_id}').get()
                    topic_name = f"{issue[:10]} - {ign} {count_tag}"
                    t_id = None
                    
                    try:
                        if perm_ref:
                            t_id = int(perm_ref)
                            bot.edit_forum_topic(ADMIN_GROUP_ID, t_id, name=topic_name)
                        else:
                            new_topic = bot.create_forum_topic(ADMIN_GROUP_ID, topic_name)
                            t_id = new_topic.message_thread_id
                            db.reference(f'player_permanent_topic/{p_id}').set(t_id)
                            player_permanent_topic[p_id] = t_id

                        db.reference(f'active_topics/{t_id}').set(p_id)
                        topic_map[t_id] = p_id
                        player_to_topic[p_id] = t_id
                        
                        t_data = {
                            'short_issue': issue[:10], 
                            'ign': ign, 
                            'count': count_tag, 
                            'issue_full': issue, 
                            'reg_no': reg_no
                        }
                        db.reference(f'topic_data/{t_id}').set(t_data)
                        topic_data[t_id] = t_data
                        
                        button_lock_tracker[t_id] = {'ask_pov': None, 'solve': None, 'reject': None}
                        
                        report = f"🚨 **NEW COMPLAINT {count_tag}**\n━━━━━━━━━━━━━━━━━━\n📝 Issue: `{issue}`\n🎮 IGN: `{ign}`\n📱 Reg: `{reg_no}`\n━━━━━━━━━━━━━━━━━━"
                        bot.send_photo(ADMIN_GROUP_ID, file_id, caption=report, message_thread_id=t_id, reply_markup=get_action_markup(t_id), parse_mode="Markdown")
                        
                        queue_ref.child(key).delete()
                        time.sleep(2.5)
                        
                    except Exception as tg_err:
                        print(f"⚠️ Telegram Error/Rate Limit: {tg_err}")
                        time.sleep(5)
                        break
            time.sleep(1.5)
        except Exception as e:
            print(f"Queue Worker Error: {e}")
            time.sleep(5)

threading.Thread(target=firebase_queue_worker, daemon=True).start()

# --- PLAYER HANDLER ---
@bot.message_handler(func=lambda message: message.chat.type == 'private', content_types=['text', 'photo', 'video', 'document'])
def handle_player_messages(message):
    p_id = message.chat.id
    if p_id in blocked_players: return

    msg_text = message.text.lower() if message.text else ""

    if p_id in player_locks:
        if time.time() < player_locks[p_id]['expiry']:
            return 
        else:
            del player_locks[p_id]

    if p_id in player_to_topic:
        t_id = player_to_topic[p_id]
        if message.content_type in ['photo', 'video', 'document']:
            bot.copy_message(ADMIN_GROUP_ID, p_id, message.message_id, message_thread_id=t_id, reply_markup=get_action_markup(t_id))
        elif message.text:
            bot.send_message(ADMIN_GROUP_ID, f"📥 **Player Reply:** {message.text}", message_thread_id=t_id)
        return

    if any(word in msg_text for word in KEYWORDS):
        start_complaint(message)

def start_complaint(message):
    p_id = message.chat.id
    if p_id in active_sessions: return 
    active_sessions.add(p_id)
    user_data = {'issue': message.text}
    msg = bot.reply_to(message, "⚠️ **Complaint Active**\n\n(1) Send Register No. ?")
    bot.register_next_step_handler(msg, get_reg_number, user_data)

def get_reg_number(message, user_data):
    user_data['reg_no'] = message.text
    msg = bot.send_message(message.chat.id, "(2) Send Your In-Game Name ?")
    bot.register_next_step_handler(msg, get_ign_step, user_data)

def get_ign_step(message, user_data):
    user_data['ign'] = message.text
    msg = bot.send_message(message.chat.id, "(3) Apna Match Join ka screenshot bhejye ?")
    bot.register_next_step_handler(msg, get_screenshot_and_send, user_data)

def get_screenshot_and_send(message, user_data):
    if message.content_type != 'photo':
        msg = bot.send_message(message.chat.id, "❌ Please screenshot bhejye ---> us match ka jo aapne tournament khelne ke liye join kiya tha ?")
        bot.register_next_step_handler(msg, get_screenshot_and_send, user_data)
        return
    
    p_id = message.chat.id
    player_complaint_counts[p_id] = player_complaint_counts.get(p_id, 0) + 1
    count_tag = get_circle_num(player_complaint_counts[p_id])
    
    try:
        ref = db.reference('complaint_queue')
        ref.push({
            'p_id': p_id,
            'issue': user_data['issue'],
            'ign': user_data['ign'],
            'reg_no': user_data['reg_no'],
            'count_tag': count_tag,
            'file_id': message.photo[-1].file_id,
            'timestamp': time.time()
        })
        bot.send_message(p_id, "✅ Don't worry (sir/mam) Hamari team aapka problem jaldi solve kar degi. Tab tak aap doosra match khel sakte ho !")
    except Exception as e: 
        bot.send_message(message.chat.id, f"❌ Error: {e}")
    finally: 
        active_sessions.discard(p_id)

# --- ADMIN CALLBACKS ---
@bot.callback_query_handler(func=lambda call: True)
def handle_admin_action(call):
    admin_id, admin_name = call.from_user.id, call.from_user.first_name
    init_admin(admin_id, admin_name)
    admin_activity[admin_id]['last_seen'] = time.time()
    
    t_id = int(call.data.split('_')[-1])
    p_id = topic_map.get(t_id)
    action_key = 'ask_pov' if "ask_pov" in call.data else 'solve' if "solve" in call.data else 'reject'
    
    if t_id in button_lock_tracker and button_lock_tracker[t_id].get(action_key):
        locked_by = admin_activity.get(button_lock_tracker[t_id][action_key], {}).get('name', "Admin")
        bot.answer_callback_query(call.id, f"❌ Yeh pehle hi {locked_by} ne click kar diya hai!", show_alert=True)
        return
    
    button_lock_tracker.setdefault(t_id, {})[action_key] = admin_id
    icon = "❓" if action_key == 'ask_pov' else "🌺" if action_key == 'solve' else "❌"
    status_text = "POV ASKED" if action_key == 'ask_pov' else "SOLVED" if action_key == 'solve' else "REJECTED"
    
    if t_id in topic_data:
        data = topic_data[t_id]
        try:
            bot.edit_forum_topic(ADMIN_GROUP_ID, t_id, name=f"{data['short_issue']} - {data['ign']} {data['count']} {icon} {admin_name[:8]}")
        except: pass
        report = f"🚨 **COMPLAINT {data['count']}**\n━━━━━━━━━━━━━━━━━━\n📝 Issue: `{data['issue_full']}`\n🎮 IGN: `{data['ign']}`\n📱 Reg: `{data['reg_no']}`\n━━━━━━━━━━━━━━━━━━\n{icon} **{status_text}** By `{admin_name}`"
        try: 
            bot.edit_message_caption(report, ADMIN_GROUP_ID, call.message.message_id, reply_markup=call.message.reply_markup, parse_mode="Markdown")
        except: pass

    working = is_working_hours()

    if "ask_pov" in call.data:
        if working: admin_activity[admin_id]['pov_asked'] += 1
        if p_id: bot.send_message(p_id, "**Admin**\n( Sir / Mam ) Abhi apna POV send karo taki ham aapka problem fix kar sake !")
    elif "solve" in call.data:
        if working: admin_activity[admin_id]['solved'] += 1
        if p_id:
            player_locks[p_id] = {"expiry": time.time() + 600} 
            if p_id in player_to_topic: del player_to_topic[p_id]
            bot.send_message(p_id, "**Admin**\n✅ Aapka problem solved ho gaya hai ( Sir / Mam )")
        db.reference(f'active_topics/{t_id}').delete()
        if t_id in topic_map: del topic_map[t_id]
    elif "reject" in call.data:
        if working: admin_activity[admin_id]['rejected'] += 1
        if p_id:
            if p_id in player_to_topic: del player_to_topic[p_id]
            bot.send_message(p_id, "**Admin**\n❌ POV missing hai, isliye aapka is problem reject kar diya gaya hai.")
        db.reference(f'active_topics/{t_id}').delete()
        if t_id in topic_map: del topic_map[t_id]

    bot.answer_callback_query(call.id, f"Action {icon} by {admin_name}")

@bot.message_handler(func=lambda message: message.chat.id == ADMIN_GROUP_ID)
def admin_group_handler(message):
    admin_id, admin_name = message.from_user.id, message.from_user.first_name
    perm = check_permission(admin_id, ADMIN_GROUP_ID)
    if not message.text: return

    if message.text == "/sync" and perm == 'owner':
        global status_message_id
        status_message_id = None
        update_admin_dashboard(ADMIN_GROUP_ID, message.message_thread_id)
    
    elif message.text == "/reset" and perm == 'owner':
        admin_activity.clear()
        bot.reply_to(message, "✅ Admin performance data has been reset to 0.")

    elif message.reply_to_message and message.message_thread_id in topic_map:
        p_id = topic_map[message.message_thread_id]
        if perm in ['owner', 'admin']:
            init_admin(admin_id, admin_name)
            if is_working_hours():
                admin_activity[admin_id]['manual_chat'] += 1
            try:
                bot.send_message(p_id, f"**Admin:** {message.text}")
            except: pass

bot.infinity_polling()
