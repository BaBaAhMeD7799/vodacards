import os
import secrets
import string
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
import telebot
from telebot import types

# ----------------- الإعدادات -----------------
BOT_TOKEN = "8786799664:AAGNS38ZHNiSoKfvOAXdgy1gRahGELaKAsU"
ADMIN_ID = 8036210671
MONGO_URI = "mongodb+srv://engahmedbakr79_db_user:fpOps4E4HpCg1tnd@bakrvfcards.iipsjbv.mongodb.net/?retryWrites=true&w=majority&appName=BAKRVFCARDS"

# ضبط الاتصال بمهلة 5 ثوانٍ لتفادي خروج Vercel عن الوقت المحدد
client = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=5000,
    socketTimeoutMS=5000,
    tlsAllowInvalidCertificates=True
)
db = client["vodafone_licenses"]
keys_col = db["keys"]

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = FastAPI(title="Vodafone Cards API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def generate_key_string():
    chars = string.ascii_uppercase + string.digits
    part1 = ''.join(secrets.choice(chars) for _ in range(4))
    part2 = ''.join(secrets.choice(chars) for _ in range(4))
    return f"VF-{part1}-{part2}"

# ----------------- لوحة تحكم تيليجرام -----------------
@bot.message_handler(commands=['start'])
def start_cmd(message):
    if message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "⛔ عذراً، هذا البوت مخصص للمسؤول فقط.")
        return

    markup = types.InlineKeyboardMarkup(row_width=2)
    b1 = types.InlineKeyboardButton("➕ إنشاء كود جديد", callback_data="btn_new_key")
    b2 = types.InlineKeyboardButton("📊 إحصائيات الأكواد", callback_data="btn_stats")
    markup.add(b1, b2)

    bot.send_message(
        message.chat.id,
        "👑 <b>لوحة تحكم تراخيص Vodafone Cards</b>\n\nاختر العملية المطلوبة من الأسفل:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    # إيقاف مؤشر التحميل على الزر في تطبيق تيليجرام فوراً
    try:
        bot.answer_callback_query(call.id)
    except Exception:
        pass

    if call.from_user.id != ADMIN_ID:
        return

    if call.data == "btn_new_key":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("1 يوم", callback_data="gen_1"),
            types.InlineKeyboardButton("7 أيام", callback_data="gen_7"),
            types.InlineKeyboardButton("30 يوم (شهر)", callback_data="gen_30"),
            types.InlineKeyboardButton("90 يوم (3 شهور)", callback_data="gen_90"),
            types.InlineKeyboardButton("دائم (سنة)", callback_data="gen_365")
        )
        bot.edit_message_text(
            "⏳ اختر مدة الكود المطلوب:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

    elif call.data.startswith("gen_"):
        days = int(call.data.split("_")[1])
        key = generate_key_string()
        try:
            keys_col.insert_one({
                "key": key,
                "duration_days": days,
                "device_id": None,
                "active": True,
                "created_at": datetime.utcnow(),
                "first_used_at": None,
                "expires_at": None
            })
            bot.send_message(
                call.message.chat.id,
                f"✅ <b>تم إنشاء كود جديد بنجاح!</b>\n\n"
                f"🔑 الكود: <code>{key}</code> (اضغط للنسخ)\n"
                f"⏳ المدة: <b>{days} يوم</b> (يبدأ العد التنازلي عند أول تفعيل)\n"
                f"📱 الربط: يربط بجهاز العميل تلقائياً عند أول فتح."
            )
        except Exception as e:
            bot.send_message(call.message.chat.id, f"⚠️ خطأ في الاتصال بقاعدة البيانات:\n<code>{str(e)}</code>")

    elif call.data == "btn_stats":
        try:
            total = keys_col.count_documents({})
            used = keys_col.count_documents({"device_id": {"$ne": None}})
            bot.send_message(
                call.message.chat.id,
                f"📊 <b>إحصائيات الأكواد:</b>\n\n"
                f"• إجمالي الأكواد: <b>{total}</b>\n"
                f"• الأكواد المفعلة على أجهزة: <b>{used}</b>\n"
                f"• الأكواد المتاحة للبيع: <b>{total - used}</b>"
            )
        except Exception as e:
            bot.send_message(call.message.chat.id, f"⚠️ خطأ في جلب الإحصائيات:\n<code>{str(e)}</code>")

# ----------------- المسارات البرمجية -----------------
@app.get("/")
@app.get("/api")
@app.get("/api/")
def home():
    return {"status": "online", "message": "Vodafone License Server is Running"}

@app.post("/")
@app.post("/api")
@app.post("/api/")
async def handle_incoming_requests(request: Request):
    try:
        body = await request.json()
    except Exception:
        return {"error": "Invalid JSON"}

    # معالجة طلبات تيليجرام
    if "update_id" in body:
        try:
            update = telebot.types.Update.de_json(body)
            bot.process_new_updates([update])
        except Exception as e:
            print("Update error:", e)
        return {"ok": True}

    # معالجة طلب فحص الكود من تطبيق Flutter
    if "key" in body and "device_id" in body:
        key_str = str(body.get("key", "")).strip()
        dev_id = str(body.get("device_id", "")).strip()

        try:
            key_doc = keys_col.find_one({"key": key_str})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

        if not key_doc:
            raise HTTPException(status_code=400, detail="❌ المفتاح غير صحيح")

        if not key_doc.get("active", True):
            raise HTTPException(status_code=403, detail="🚫 تم إيقاف هذا المفتاح")

        now = datetime.utcnow()

        if not key_doc.get("first_used_at"):
            expires = now + timedelta(days=key_doc["duration_days"])
            keys_col.update_one(
                {"_id": key_doc["_id"]},
                {"$set": {
                    "device_id": dev_id,
                    "first_used_at": now,
                    "expires_at": expires
                }}
            )
            return {
                "status": "success",
                "message": "تم التفعيل بنجاح",
                "expires_at": expires.isoformat()
            }

        if key_doc.get("device_id") != dev_id:
            raise HTTPException(status_code=403, detail="⚠️ هذا المفتاح مستخدم على جهاز آخر")

        if now > key_doc["expires_at"]:
            raise HTTPException(status_code=403, detail="⏳ انتهت صلاحية المفتاح")

        return {
            "status": "success",
            "message": "المفتاح صالح",
            "expires_at": key_doc["expires_at"].isoformat()
        }

    return {"message": "Unknown request format"}
