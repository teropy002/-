import os
import sqlite3
import zipfile
import shutil
from functools import wraps
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- 설정 ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") 
SUPREME_ADMIN = int(os.environ.get("SUPREME_ADMIN"))
DB_FILE = "files.db"

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
            return # 본인이 아니면 무반응
        return await func(update, context, *args, **kwargs)
    return wrapped

# --- 파일 및 워터마크 로직 ---
def inject_watermark(in_path, out_path, user_id):
    """파일 변조 방지 및 추적 ID 삽입"""
    shutil.copyfile(in_path, out_path)
    with zipfile.ZipFile(out_path, 'a', zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"META-INF/security_{user_id}.txt", f"UID:{user_id}")

# --- 명령어 핸들러 ---
@restricted
async def cmd_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """관리자가 명령하면 목록을 그룹에 게시하고 고정"""
    cursor.execute("SELECT name FROM file_list")
    files = [row[0] for row in cursor.fetchall()]
    
    if not files:
        await update.message.reply_text("목록이 비어있습니다.")
        return
    
    msg_text = "📄 **현재 보유 파일 목록**:\n\n" + "\n".join([f"• {f}" for f in files])
    sent_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text=msg_text, parse_mode="Markdown")
    await context.bot.pin_chat_message(chat_id=update.effective_chat.id, message_id=sent_msg.message_id)

async def doc_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """파일 자동 감지 및 목록 저장"""
    doc = update.message.document
    if doc:
        try:
            cursor.execute("INSERT INTO file_list (name) VALUES (?)", (doc.file_name,))
            conn.commit()
            print(f"저장된 파일: {doc.file_name}")
        except sqlite3.IntegrityError:
            pass # 이미 존재함

# --- 메인 실행 ---
if __name__ == '__main__':
    app = Application.builder().token(TOKEN).build()

    # 본인만 가능한 명령어
    app.add_handler(CommandHandler("post", cmd_post))
    
    # 누구나 파일 업로드 시 감지
    app.add_handler(MessageHandler(filters.Document.ALL, doc_handler))

    print("봇이 시작되었습니다.")
    app.run_polling()
