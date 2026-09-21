import os
import secrets
import string
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pymongo import MongoClient
import telebot
from telebot import types
import uvicorn
import threading

# ----------------- الإعدادات الخاصة بك -----------------
BOT_TOKEN = os.getenv("BOT_TOKEN", "8786799664:AAGNS38ZHNiSoKfvOAXdgy1gRahGELaKAsU")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8036210671"))
MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb+srv://engahmedbakr79_db_user:fpOps4E4HpCg1tnd@bakrvfcards.iipsjbv.mongodb.net/?retryWrites=true&w=majority&appName=BAKRVFCARDS"
)

# ----------------- تهيئة السيرفر وقاعدة البيانات -----------------
client = MongoClient(MONGO_URI)
db = client["vodafone_licenses"]
keys_col = db["keys"]

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = FastAPI(title="Vodafone Cards License Server")

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

    elif call.data == "btn_stats":
        total = keys_col.count_documents({})
        used = keys_col.count_documents({"device_id": {"$ne": None}})
        bot.send_message(
            call.message.chat.id,
            f"📊 <b>إحصائيات الأكواد:</b>\n\n"
            f"• إجمالي الأكواد: <b>{total}</b>\n"
            f"• الأكواد المفعلة على أجهزة: <b>{used}</b>\n"
            f"• الأكواد المتاحة للبيع: <b>{total - used}</b>"
        )

# ----------------- API الخاص بتطبيق Flutter -----------------
@app.get("/")
def root():
    return {"status": "online", "service": "Vodafone Cards License API"}

class VerifyRequest(BaseModel):
    key: str
    device_id: str

@app.post("/api/verify")
async def verify_license(req: VerifyRequest):
    key_doc = keys_col.find_one({"key": req.key.strip()})

    if not key_doc:
        raise HTTPException(status_code=400, detail="❌ المفتاح غير صحيح")

    if not key_doc.get("active", True):
        raise HTTPException(status_code=403, detail="🚫 تم إيقاف هذا المفتاح")

    now = datetime.utcnow()

    # أول استخدام وتفعيل للكود
    if not key_doc.get("first_used_at"):
        expires = now + timedelta(days=key_doc["duration_days"])
        keys_col.update_one(
            {"_id": key_doc["_id"]},
            {"$set": {
                "device_id": req.device_id,
                "first_used_at": now,
                "expires_at": expires
            }}
        )
        return {
            "status": "success",
            "message": "تم التفعيل بنجاح",
            "expires_at": expires.isoformat()
        }

    # التحقق من أن الجهاز هو نفس الجهاز المسجل
    if key_doc.get("device_id") != req.device_id:
        raise HTTPException(status_code=403, detail="⚠️ هذا المفتاح مستخدم على جهاز آخر")

    # التحقق من انتهاء الصلاحية
    if now > key_doc["expires_at"]:
        raise HTTPException(status_code=403, detail="⏳ انتهت صلاحية المفتاح")

    return {
        "status": "success",
        "message": "المفتاح صالح",
        "expires_at": key_doc["expires_at"].isoformat()
    }

def run_bot():
    bot.infinity_polling(skip_pending=True)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
