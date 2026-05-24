import os
import sqlite3
from functools import wraps
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- 설정 ---
# Railway Variables에 등록된 환경 변수를 불러옵니다.
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
# 본인 ID는 보안을 위해 환경 변수로 관리하세요.
SUPREME_ADMIN = int(os.environ.get("SUPREME_ADMIN", 6860788088))
# DB 파일을 Railway Volume 경로(/app)로 고정합니다.
DB_FILE = "/app/files.db"

# --- 데이터베이스 초기화 ---
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS file_list (name TEXT PRIMARY KEY)")
conn.commit()

# --- 보안 데코레이터 ---
def restricted(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user.id != SUPREME_ADMIN:
            return 
        return await func(update, context, *args, **kwargs)
    return wrapped

# --- 핸들러 ---
@restricted
async def cmd_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """목록 조회 및 그룹 고정"""
    cursor.execute("SELECT name FROM file_list")
    files = [row[0] for row in cursor.fetchall()]
    
    if not files:
        await update.message.reply_text("📄 목록이 비어있습니다.")
        return
    
    msg_text = "📄 **현재 보유 파일 목록**:\n\n" + "\n".join([f"• {f}" for f in files])
    sent_msg = await context.bot.send_message(
        chat_id=update.effective_chat.id, 
        text=msg_text, 
        parse_mode="Markdown"
    )
    # 메시지 고정 시도
    try:
        await context.bot.pin_chat_message(chat_id=update.effective_chat.id, message_id=sent_msg.message_id)
    except Exception as e:
        print(f"고정 실패 (권한 확인 필요): {e}")

async def doc_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """파일 감지 및 저장"""
    if update.message and update.message.document:
        doc = update.message.document
        try:
            cursor.execute("INSERT INTO file_list (name) VALUES (?)", (doc.file_name,))
            conn.commit()
            print(f"저장 성공: {doc.file_name}")
            await update.message.reply_text(f"✅ 저장 완료: {doc.file_name}")
        except sqlite3.IntegrityError:
            await update.message.reply_text(f"⚠️ 이미 목록에 있습니다: {doc.file_name}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == SUPREME_ADMIN:
        await update.message.reply_text("봇이 정상 작동 중입니다.")

# --- 메인 실행 ---
if __name__ == '__main__':
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("post", cmd_post))
    app.add_handler(MessageHandler(filters.Document.ALL, doc_handler))

    print("봇이 시작되었습니다.")
    app.run_polling()
