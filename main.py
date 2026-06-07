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
BANLIST_TOPIC_ID = 1794  # Automatic banlist topic ID
KOLKATA = pytz.timezone('Asia/Kolkata')
FIREBASE_DB_URL = 'https://fullmap-903ce-default-rtdb.asia-southeast1.firebasedatabase.app/'

# --- FIREBASE INITIALIZE ---
cred = credentials.Certificate("credentials.json")
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': FIREBASE_DB_URL
    })

bot = telebot.TeleBot(API_TOKEN)
bot.remove_webhook() 

# --- THREAD SAFE LOCKS ---
data_lock = threading.Lock()

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
        if status in ['creator', 'administrator']: return 'admin' if status == 'administrator' else 'owner'
        return 'member'
    except: return 'member'

def get_action_markup(t_id):
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.row(
        types.InlineKeyboardButton("❓ POV", callback_data=f"ask_pov_{t_id}"),
        types.InlineKeyboardButton("🌺 Solve", callback_data=f"solve_{t_id}"),
        types.InlineKeyboardButton("❌ Reject", callback_data=f"reject_{t_id}")
    )
    markup.row(
        types.InlineKeyboardButton("⌛ Wait", callback_data=f"wait_{t_id}"),
        types.InlineKeyboardButton("🚫 Block", callback_data=f"block_{t_id}"),
        types.InlineKeyboardButton("♻️ Unblock", callback_data=f"unblock_{t_id}")
    )
    return markup

def get_permanent_ban_markup(p_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton("🚫 Ban", callback_data=f"permban_{p_id}"),
        types.InlineKeyboardButton("♻️ Unblock", callback_data=f"permunb_{p_id}")
    )
    return markup

# --- DASHBOARD ---
def update_admin_dashboard(chat_id, thread_id=1):
    global status_message_id
    text = "📊 **ADMIN LIVE PERFORMANCE BAR**\n━━━━━━━━━━━━━━━━━━━━\n"
    
    with data_lock:
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
    with data_lock:
        if admin_id not in admin_activity:
            current = time.time()
            admin_activity[admin_id] = {
                'name': name, 'solved': 0, 'rejected': 0, 'pov_asked': 0, 'manual_chat': 0,
                'last_seen': current, 'last_update_tick': current,
                'total_online_time': 0, 'total_offline_time': 0
            }

def scheduler_loop():
    schedule.every().day.at("23:00").do(update_admin_dashboard, chat_id=ADMIN_GROUP_ID)
    while True:
        schedule.run_pending()
        time.sleep(60)

threading.Thread(target=scheduler_loop, daemon=True).start()

# --- AUTOMATIC SAFE CLEANUP WORKER ---
def auto_cleanup_worker():
    print("🧹 Auto-Cleanup Worker Shield Activated...")
    while True:
        try:
            completed_ref = db.reference('completed_topics')
            completed_topics = completed_ref.get()
            active_topics = db.reference('active_topics').get() or {}
            
            if completed_topics:
                now = time.time()
                for t_id, data in completed_topics.items():
                    if now - data['timestamp'] > 259200:
                        if str(t_id) in active_topics or int(t_id) in active_topics:
                            completed_ref.child(t_id).delete() 
                            continue
                        try:
                            bot.delete_forum_topic(ADMIN_GROUP_ID, int(t_id))
                            completed_ref.child(t_id).delete()
                            p_id_linked = data.get('p_id')
                            if p_id_linked:
                                db.reference(f'player_permanent_topic/{p_id_linked}').delete()
                            print(f"🧹 Successfully cleaned up 3 days old topic: {t_id}")
                        except Exception as tg_err:
                            print(f"⚠️ Telegram cleanup bypass for {t_id}: {tg_err}")
                            completed_ref.child(t_id).delete()
        except Exception as e:
            print(f"Cleanup Worker Error: {e}")
        time.sleep(1800) 

threading.Thread(target=auto_cleanup_worker, daemon=True).start()

# --- BACKGROUND FIREBASE WORKER ---
def firebase_queue_worker():
    global topic_map, player_to_topic, topic_data, player_permanent_topic
    print("🚀 Background Queue Worker Active!")
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
                            try:
                                bot.edit_forum_topic(ADMIN_GROUP_ID, t_id, name=topic_name)
                            except:
                                new_topic = bot.create_forum_topic(ADMIN_GROUP_ID, topic_name)
                                t_id = new_topic.message_thread_id
                                db.reference(f'player_permanent_topic/{p_id}').set(t_id)
                        else:
                            new_topic = bot.create_forum_topic(ADMIN_GROUP_ID, topic_name)
                            t_id = new_topic.message_thread_id
                            db.reference(f'player_permanent_topic/{p_id}').set(t_id)
                            with data_lock:
                                player_permanent_topic[p_id] = t_id

                        db.reference(f'active_topics/{t_id}').set(p_id)
                        
                        with data_lock:
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
                        with data_lock:
                            topic_data[t_id] = t_data
                            button_lock_tracker[t_id] = {'ask_pov': None, 'solve': None, 'reject': None, 'wait': None, 'block': None, 'unblock': None}
                        
                        # Added click-to-copy backticks for dynamic complaint reporting details
                        report = f"🚨 **NEW COMPLAINT {count_tag}**\n━━━━━━━━━━━━━━━━━━\n📝 Issue: `{issue}`\n🎮 IGN: `{ign}`\n📱 Reg: `{reg_no}`\n━━━━━━━━━━━━━━━━━━"
                        bot.send_photo(ADMIN_GROUP_ID, file_id, caption=report, message_thread_id=t_id, reply_markup=get_action_markup(t_id), parse_mode="Markdown")
                        
                        queue_ref.child(key).delete()
                        time.sleep(0.2)
                        
                    except Exception as tg_err:
                        print(f"⚠️ Telegram Error Encountered: {tg_err}")
                        time.sleep(3)
                        continue 
            time.sleep(0.3)
        except Exception as e:
            print(f"Queue Worker Error: {e}")
            time.sleep(2)

threading.Thread(target=firebase_queue_worker, daemon=True).start()

# --- PLAYER HANDLER ---
@bot.message_handler(func=lambda message: message.chat.type == 'private', content_types=['text', 'photo', 'video', 'document'])
def handle_player_messages(message):
    p_id = message.chat.id
    
    if db.reference(f'master_banlist/{p_id}').get():
        return

    msg_text = message.text.lower() if message.text else ""

    if p_id in player_locks:
        if time.time() < player_locks[p_id]['expiry']:
            return 
        else:
            with data_lock:
                del player_locks[p_id]

    is_active_player = False
    with data_lock:
        is_active_player = p_id in player_to_topic
        if is_active_player:
            t_id = player_to_topic[p_id]

    if is_active_player:
        if message.content_type in ['photo', 'video', 'document']:
            bot.copy_message(ADMIN_GROUP_ID, p_id, message.message_id, message_thread_id=t_id, reply_markup=get_action_markup(t_id))
        elif message.text:
            bot.send_message(ADMIN_GROUP_ID, f"📥 **Player Reply:** {message.text}", message_thread_id=t_id)
        return

    if any(word in msg_text for word in KEYWORDS):
        start_complaint(message)

def start_complaint(message):
    p_id = message.chat.id
    with data_lock:
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
    with data_lock:
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
        with data_lock:
            active_sessions.discard(p_id)

# --- ADMIN CALLBACKS ---
@bot.callback_query_handler(func=lambda call: call.data.startswith(('ask_pov_', 'solve_', 'reject_', 'wait_', 'block_', 'unblock_')))
def handle_admin_action(call):
    admin_id, admin_name = call.from_user.id, call.from_user.first_name
    perm = check_permission(admin_id, ADMIN_GROUP_ID)
    
    restricted_buttons = ["solve", "reject", "block", "unblock"]
    is_restricted = any(res in call.data for res in restricted_buttons)
    
    if is_restricted and perm not in ['owner', 'admin']:
        bot.answer_callback_query(call.id, "⚠️ Yeh button sirf Admin aur Owner ke liye hai!", show_alert=True)
        return

    init_admin(admin_id, admin_name)
    with data_lock:
        admin_activity[admin_id]['last_seen'] = time.time()
    
    parts = call.data.split('_')
    action_key = parts[0] if parts[0] != "ask" else "ask_pov"
    t_id = int(parts[-1])
    
    with data_lock:
        p_id = topic_map.get(t_id)
        
    if not p_id:
        p_id = db.reference(f'active_topics/{t_id}').get()
    if not p_id:
        comp_data = db.reference(f'completed_topics/{t_id}').get()
        if comp_data and isinstance(comp_data, dict):
            p_id = comp_data.get('p_id')
    
    with data_lock:
        if action_key not in ['unblock', 'block'] and t_id in button_lock_tracker and button_lock_tracker[t_id].get(action_key):
            locked_by = admin_activity.get(button_lock_tracker[t_id][action_key], {}).get('name', "Admin")
            bot.answer_callback_query(call.id, f"❌ Yeh pehle hi {locked_by} ne click kar diya hai!", show_alert=True)
            return
        button_lock_tracker.setdefault(t_id, {})[action_key] = admin_id
    
    icons = {"ask_pov": "❓", "solve": "🌺", "reject": "❌", "wait": "⌛", "block": "🚫", "unblock": "♻️"}
    status_texts = {"ask_pov": "POV ASKED", "solve": "SOLVED", "reject": "REJECTED", "wait": "WAIT APPLIED", "block": "BLOCKED", "unblock": "UNBLOCKED"}
    
    icon = icons[action_key]
    status_text = status_texts[action_key]
    
    has_data = False
    with data_lock:
        if t_id in topic_data:
            has_data = True
            data = topic_data[t_id]
            
    if not has_data:
        fb_t_data = db.reference(f'topic_data/{t_id}').get()
        if fb_t_data:
            has_data = True
            data = fb_t_data
            with data_lock:
                topic_data[t_id] = data

    if has_data:
        try:
            bot.edit_forum_topic(ADMIN_GROUP_ID, t_id, name=f"{data['short_issue']} - {data['ign']} {data['count']} {icon} {admin_name[:8]}")
        except: pass
        # Added click-to-copy formatting backticks for general admin panel logs too
        report = f"🚨 **COMPLAINT {data['count']}**\n━━━━━━━━━━━━━━━━━━\n📝 Issue: `{data['issue_full']}`\n🎮 IGN: `{data['ign']}`\n📱 Reg: `{data['reg_no']}`\n━━━━━━━━━━━━━━━━━━\n{icon} **{status_text}** By `{admin_name}`"
        try: 
            bot.edit_message_caption(report, ADMIN_GROUP_ID, call.message.message_id, reply_markup=call.message.reply_markup, parse_mode="Markdown")
        except: pass

    working = is_working_hours()

    if action_key == "ask_pov":
        if working: 
            with data_lock: admin_activity[admin_id]['pov_asked'] += 1
        if p_id: bot.send_message(p_id, "**Admin**\n( Sir / Mam ) Abhi apna POV send karo taki ham aapka problem fix kar sake !")
        
    elif action_key == "wait":
        if p_id: bot.send_message(p_id, "⌛ Apko Thora wait kar na padega apka problem jabtak verify na ho jaye !")
        
    elif action_key == "block":
        if p_id and has_data: 
            db.reference(f'master_banlist/{p_id}').set({
                'reg_no': data['reg_no'],
                'ign': data['ign'],
                'blocked_by': admin_name,
                'timestamp': time.time()
            })
            bot.send_message(p_id, "Note : Policy Violation Activity 🚫 Booyah Battle Tournament se ban kiya jara hai - Thanks For Understanding 📥")
            
            # ALL fields (Reg, IGN, ID, Manual Command suggestion) are wrapped with backticks for instant 1-click copy
            ban_card = (f"🚫 **BOOYAH BATTLE BANLIST PROFILE**\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"📱 **Reg:** `{data['reg_no']}`\n"
                        f"🎮 **IGN:** `{data['ign']}`\n"
                        f"🆔 **ID:** `{p_id}`\n"
                        f"👤 **Blocked By:** `{admin_name}`\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"🚫 **BLOCKED By** `{admin_name}`\n\n"
                        f"💡 Quick command: `/ub {data['reg_no']}`")
            
            try:
                bot.send_message(ADMIN_GROUP_ID, ban_card, message_thread_id=BANLIST_TOPIC_ID, reply_markup=get_permanent_ban_markup(p_id), parse_mode="Markdown")
            except Exception as e:
                print(f"Error sending ban card: {e}")

            with data_lock:
                if p_id in player_to_topic: del player_to_topic[p_id]
            db.reference(f'player_permanent_topic/{p_id}').delete()
        db.reference(f'active_topics/{t_id}').delete()
        with data_lock:
            if t_id in topic_map: del topic_map[t_id]
        
    elif action_key == "unblock":
        if p_id:
            db.reference(f'master_banlist/{p_id}').delete()
            unban_sms = "( Sorry Sir / Mam )\nAapko Booyah Battle se Unban kiya gaya hai ✅ \nSorry For Misunderstanding ❣️ 📥"
            bot.send_message(p_id, unban_sms)

    elif action_key == "solve":
        if working: 
            with data_lock: admin_activity[admin_id]['solved'] += 1
        if p_id:
            with data_lock:
                player_locks[p_id] = {"expiry": time.time() + 600}
                if p_id in player_to_topic: del player_to_topic[p_id]
            bot.send_message(p_id, "**Admin**\n✅ Aapka problem solved ho gaya hai ( Sir / Mam )")
        db.reference(f'completed_topics/{t_id}').set({'timestamp': time.time(), 'p_id': p_id})
        db.reference(f'active_topics/{t_id}').delete()
        with data_lock:
            if t_id in topic_map: del topic_map[t_id]
        
    elif action_key == "reject":
        if working: 
            with data_lock: admin_activity[admin_id]['rejected'] += 1
        if p_id:
            with data_lock:
                if p_id in player_to_topic: del player_to_topic[p_id]
            bot.send_message(p_id, "**Admin**\n❌ POV missing hai, isliye aapka is problem reject kar diya gaya hai.")
        db.reference(f'completed_topics/{t_id}').set({'timestamp': time.time(), 'p_id': p_id})
        db.reference(f'active_topics/{t_id}').delete()
        with data_lock:
            if t_id in topic_map: del topic_map[t_id]

    bot.answer_callback_query(call.id, f"Action {icon} by {admin_name}")

# --- BANLIST CARD DE-ATTACHED MULTI-LOOP HANDLER (BAN / UNBAN BOTH BUTTONS RETAINED) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith(('permban_', 'permunb_')))
def handle_permanent_ban_unban_loops(call):
    admin_id, admin_name = call.from_user.id, call.from_user.first_name
    perm = check_permission(admin_id, ADMIN_GROUP_ID)
    
    if perm not in ['owner', 'admin']:
        bot.answer_callback_query(call.id, "⚠️ Access Denied! Sirf Admin ya Owner hi action le sakte hain.", show_alert=True)
        return
        
    action, target_p_id = call.data.split('_')
    current_text = call.message.text
    
    # Text parsing with strict inline copy preservation blocks
    lines = current_text.split('\n')
    base_lines = []
    reg_val, ign_val = "None", "None"
    
    for line in lines:
        if "Blocked By:" in line or "UNBLOCKED By" in line or "BLOCKED By" in line or "━━━━━━━━━━━━━━━━━━" in line or "Quick command:" in line:
            continue
        if "Reg:" in line:
            reg_val = line.split("`")[1] if "`" in line else line.split(":")[-1].strip()
        if "IGN:" in line:
            ign_val = line.split("`")[1] if "`" in line else line.split(":")[-1].strip()
            
        if line.strip():
            base_lines.append(line)
            
    # Clean rebuild matching the layout pattern precisely
    rebuilt_base = (f"🚫 **BOOYAH BATTLE BANLIST PROFILE**\n"
                    f"📱 **Reg:** `{reg_val}`\n"
                    f"🎮 **IGN:** `{ign_val}`\n"
                    f"🆔 **ID:** `{target_p_id}`")

    # --- BUTTON BAN CLICKED ---
    if action == "permban":
        is_banned = db.reference(f'master_banlist/{target_p_id}').get()
        if is_banned:
            bot.answer_callback_query(call.id, "ℹ️ Player pehle se hi Banned hai!")
            return
            
        db.reference(f'master_banlist/{target_p_id}').set({
            'blocked_by': admin_name,
            'timestamp': time.time(),
            'reg_no': reg_val,
            'ign': ign_val
        })
        
        try:
            bot.send_message(int(target_p_id), "Note : Policy Violation Activity 🚫 Booyah Battle Tournament se ban kiya jara hai - Thanks For Understanding 📥")
        except: pass
        
        bot.answer_callback_query(call.id, "🚫 Player Banned successfully!")
        
        updated_text = (f"{rebuilt_base}\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"👤 **Blocked By:** `{admin_name}`\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"🚫 **BLOCKED By** `{admin_name}`\n\n"
                        f"💡 Quick command: `/ub {reg_val}`")
                        
    # --- BUTTON UNBLOCK CLICKED ---
    elif action == "permunb":
        is_banned = db.reference(f'master_banlist/{target_p_id}').get()
        if not is_banned:
            bot.answer_callback_query(call.id, "ℹ️ Player pehle se hi Unbanned hai!")
            return
            
        db.reference(f'master_banlist/{target_p_id}').delete()
        
        unban_sms = "( Sorry Sir / Mam )\nAapko Booyah Battle se Unban kiya gaya hai ✅ \nSorry For Misunderstanding ❣️ 📥"
        try:
            bot.send_message(int(target_p_id), unban_sms)
        except: pass
        
        bot.answer_callback_query(call.id, "♻️ Player Unbanned successfully!")
        
        updated_text = (f"{rebuilt_base}\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"👤 **Blocked By:** `None`\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"♻️ **UNBLOCKED By** `{admin_name}`\n\n"
                        f"💡 Quick command: `/b {reg_val}`")

    try:
        bot.edit_message_text(updated_text, call.message.chat.id, call.message.message_id, reply_markup=call.message.reply_markup, parse_mode="Markdown")
    except Exception as e:
        pass

# --- MANUAL COMMANDS HANDLER (/b & /ub) ---
@bot.message_handler(func=lambda message: message.chat.id == ADMIN_GROUP_ID and message.text and message.text.startswith(('/b ', '/ub ')))
def handle_manual_ban_unban(message):
    admin_id, admin_name = message.from_user.id, message.from_user.first_name
    perm = check_permission(admin_id, ADMIN_GROUP_ID)
    
    if perm not in ['owner', 'admin']:
        bot.reply_to(message, "⚠️ Yeh command sirf Admins aur Owner ke liye hai!")
        return

    parts = message.text.split(maxsplit=1)
    command = parts[0]
    search_reg = parts[1].strip()

    # --- /b MANUAL BAN LOGIC ---
    if command == "/b":
        found_player = None
        
        with data_lock:
            for t_id, data in topic_data.items():
                if str(data.get('reg_no')) == search_reg:
                    p_id = topic_map.get(t_id)
                    if p_id:
                        found_player = {'p_id': p_id, 'reg_no': search_reg, 'ign': data.get('ign')}
                        break
                        
        if not found_player:
            active_fb = db.reference('topic_data').get()
            if active_fb:
                for t_id, d in active_fb.items():
                    if str(d.get('reg_no')) == search_reg:
                        p_id = db.reference(f'active_topics/{t_id}').get()
                        if p_id:
                            found_player = {'p_id': p_id, 'reg_no': search_reg, 'ign': d.get('ign')}
                            break

        if not found_player:
            bot.reply_to(message, f"❌ Register Number `{search_reg}` active complaint session mein nahi mila.")
            return

        p_id = found_player['p_id']
        ign = found_player['ign']

        db.reference(f'master_banlist/{p_id}').set({
            'reg_no': search_reg,
            'ign': ign,
            'blocked_by': admin_name,
            'timestamp': time.time()
        })
        
        try:
            bot.send_message(p_id, "Note : Policy Violation Activity 🚫 Booyah Battle Tournament se ban kiya jara hai - Thanks For Understanding 📥")
        except: pass

        # All values wrapped inside markdown mono ticks for lightning-fast copy
        ban_card = (f"🚫 **BOOYAH BATTLE BANLIST PROFILE**\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"📱 **Reg:** `{search_reg}`\n"
                    f"🎮 **IGN:** `{ign}`\n"
                    f"🆔 **ID:** `{p_id}`\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"🚫 **BLOCKED By** `{admin_name}`\n\n"
                    f"💡 Quick command: `/ub {search_reg}`")
        
        try:
            bot.send_message(ADMIN_GROUP_ID, ban_card, message_thread_id=BANLIST_TOPIC_ID, reply_markup=get_permanent_ban_markup(p_id), parse_mode="Markdown")
            bot.reply_to(message, f"✅ Player `{search_reg}` ko manually ban karke profile cards topic {BANLIST_TOPIC_ID} mein bhej di gayi hai.")
        except Exception as e:
            bot.reply_to(message, f"⚠️ Card sent error: {e}")

        with data_lock:
            if p_id in player_to_topic: del player_to_topic[p_id]
        db.reference(f'player_permanent_topic/{p_id}').delete()
        
        with data_lock:
            for t_id, p in list(topic_map.items()):
                if p == p_id:
                    db.reference(f'active_topics/{t_id}').delete()
                    del topic_map[t_id]

    # --- /ub MANUAL UNBAN LOGIC ---
    elif command == "/ub":
        master_list = db.reference('master_banlist').get()
        target_p_id = None
        
        if master_list:
            for p, d in master_list.items():
                if str(d.get('reg_no')) == search_reg:
                    target_p_id = p
                    break

        if not target_p_id:
            bot.reply_to(message, f"❌ Banned list mein Register Number `{search_reg}` ka koi record nahi mila.")
            return

        db.reference(f'master_banlist/{target_p_id}').delete()
        
        unban_sms = "( Sorry Sir / Mam )\nAapko Booyah Battle se Unban kiya gaya hai ✅ \nSorry For Misunderstanding ❣️ 📥"
        try:
            bot.send_message(int(target_p_id), unban_sms)
        except: pass

        # Monospace player ID inside output confirmation text for easy picking
        success_msg = (f"✅ **Player `{target_p_id}` Unbanned Successfully!**\n\n"
                       f"Sms sent to player, now they can register new complaints.")
        bot.send_message(ADMIN_GROUP_ID, success_msg, message_thread_id=message.message_thread_id, parse_mode="Markdown")

# --- ADMIN GENERAL CHAT HANDLER ---
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
        with data_lock:
            admin_activity.clear()
        bot.reply_to(message, "✅ Admin performance data has been reset to 0.")

    elif message.reply_to_message:
        with data_lock:
            is_mapped_topic = message.message_thread_id in topic_map
            if is_mapped_topic:
                p_id = topic_map[message.message_thread_id]
                
        if is_mapped_topic and perm in ['owner', 'admin']:
            init_admin(admin_id, admin_name)
            if is_working_hours():
                with data_lock:
                    admin_activity[admin_id]['manual_chat'] += 1
            try:
                bot.send_message(p_id, f"**Admin:** {message.text}")
            except: pass

bot.infinity_polling()
