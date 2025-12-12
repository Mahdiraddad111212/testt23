import uuid
import asyncio
import re
import os
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

# ================== CONSTANTS ==================
BOT_TOKEN = "8218817014:AAEwJmJzfs2djXJhG4PbJXMg1YLDC0DC_mk"
GEMINI_API_KEY = "AIzaSyAYHyGSzffQaNodFdP5J6X_q3ndLugtWYM"

MAX_PARALLEL = 10
TARGET_GROUP_ID = -5080877762

# ================== GEMINI CONFIG ==================
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-3-pro-preview")

# ================== GLOBAL STATE ==================
all_answers_by_chat = {}
active_tasks_by_chat = {}
semaphores_by_chat = {}

ANSWER_REGEX = re.compile(r"^(\d+)-\([A-Z]\)-.+$")

# ================== BLOCKING GEMINI ==================
def gemini_solve(image_path: str) -> str:
    prompt = """
You are a senior university examiner specializing ONLY in Physics and Chemistry.

The image contains ONE multiple-choice question.

STRICT OUTPUT FORMAT:
questionNumber-(AnswerLetter)-AnswerText

RULES:
- Output EXACTLY one line
- No explanation
- No calculations
- No equations or units
- Short exam-style answer
- If not Physics or Chemistry, output:
INVALID-SUBJECT
"""

    with open(image_path, "rb") as img:
        response = model.generate_content(
            [
                {"text": prompt},
                {"mime_type": "image/jpeg", "data": img.read()}
            ]
        )

    if response.candidates:
        for part in response.candidates[0].content.parts:
            if hasattr(part, "text") and part.text.strip():
                return part.text.strip().splitlines()[0]

    return "FORMAT-ERROR"

# ================== SEND FINAL SUMMARY ==================
async def send_final_summary(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    answers = all_answers_by_chat.get(chat_id, [])
    if not answers:
        return

    valid_answers = [a for a in answers if a not in ("FORMAT-ERROR", "INVALID-SUBJECT")]

    def extract_number(ans):
        m = ANSWER_REGEX.match(ans)
        return int(m.group(1)) if m else 9999

    valid_answers.sort(key=extract_number)

    summary = "📌 الملخص النهائي لجميع الإجابات:\n\n" + "\n".join(valid_answers)

    await context.bot.send_message(chat_id=chat_id, text=summary)

    all_answers_by_chat[chat_id] = []

# ================== IMAGE / DOCUMENT HANDLER ==================
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id

    all_answers_by_chat.setdefault(chat_id, [])
    active_tasks_by_chat.setdefault(chat_id, 0)
    semaphores_by_chat.setdefault(chat_id, asyncio.Semaphore(MAX_PARALLEL))

    semaphore = semaphores_by_chat[chat_id]

    # رسالة الحالة
    status_msg = await update.message.reply_text("جاري حل السؤال ⏳")

    # تحديد الملف (صورة أو Document)
    if update.message.photo:
        file = await update.message.photo[-1].get_file()
    elif update.message.document and update.message.document.mime_type.startswith("image/"):
        file = await update.message.document.get_file()
    else:
        await context.bot.edit_message_text(
            chat_id=status_msg.chat_id,
            message_id=status_msg.message_id,
            text="❌ الملف غير مدعوم"
        )
        return

    active_tasks_by_chat[chat_id] += 1

    async with semaphore:
        image_path = f"q_{update.message.message_id}_{uuid.uuid4().hex}.jpg"
        await file.download_to_drive(image_path)

        answer = await asyncio.to_thread(gemini_solve, image_path)

        # 🔥 إرسال الصورة إلى القروب مع الإجابة في الكابتشن
        try:
            with open(image_path, "rb") as img_file:
                await context.bot.send_photo(
                    chat_id=TARGET_GROUP_ID,
                    photo=img_file,
                    caption=answer
                )
        except Exception:
            pass

        # حذف الصورة
        try:
            os.remove(image_path)
        except Exception:
            pass

    active_tasks_by_chat[chat_id] -= 1
    all_answers_by_chat[chat_id].append(answer)

    # تعديل رسالة الحالة
    await context.bot.edit_message_text(
        chat_id=status_msg.chat_id,
        message_id=status_msg.message_id,
        text=f"تم حل السؤال ✅\n{answer}"
    )

    # إرسال الملخص النهائي عند انتهاء جميع المهام
    if active_tasks_by_chat[chat_id] == 0:
        await send_final_summary(chat_id, context)

# ================== MAIN ==================
def main():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(20)
        .build()
    )

    app.add_handler(
        MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_image)
    )

    print("✅ Telegram Bot is running (SEND TO GROUP MODE)...")
    app.run_polling()

if __name__ == "__main__":
    main()
