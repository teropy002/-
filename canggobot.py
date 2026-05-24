import os
import sqlite3
import html
import logging
from functools import wraps
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- 로깅 설정 ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 설정 ---
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
SUPREME_ADMIN = int(os.environ.get("SUPREME_ADMIN", 6860788088))

# DB 경로: Railway Volume (/data) 우선, 없으면 로컬 경로 사용
if os.path.exists("/data"):
    DB_FILE = "/data/files.db"
elif os.path.exists("/app"):
    DB_FILE = "/app/files.db"
else:
    DB_FILE = os.path.join(os.getcwd(), "files.db")

logger.info(f"Using database at: {DB_FILE}")

# --- 데이터베이스 초기화 ---
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS file_list (name TEXT PRIMARY KEY)")
conn.commit()

# --- 보안 데코레이터 ---
def restricted(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != SUPREME_ADMIN:
            logger.warning(f"Unauthorized access attempt by ID: {user_id}")
            return 
        return await func(update, context, *args, **kwargs)
    return wrapped

# --- 핸들러 ---
@restricted
async def cmd_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """목록 조회 및 그룹 고정"""
    try:
        cursor.execute("SELECT name FROM file_list")
        files = [row[0] for row in cursor.fetchall()]
        
        if not files:
            await update.message.reply_text("📄 목록이 비어 있습니다.")
            return
        
        # 파일명 HTML 이스케이프 처리 (특수문자 오류 방지)
        file_list_text = "\n".join([f"• {html.escape(f)}" for f in files])
        msg_text = f"📄 <b>현재 파일 목록</b>:\n\n{file_list_text}"
        
        sent_msg = await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text=msg_text, 
            parse_mode="HTML"
        )
        
        # 메시지 고정 시도
        try:
            await context.bot.pin_chat_message(chat_id=update.effective_chat.id, message_id=sent_msg.message_id)
        except Exception as e:
            logger.error(f"고정 실패: {e}")
            
    except Exception as e:
        logger.error(f"cmd_post 오류: {e}")
        await update.message.reply_text(f"❌ 오류 발생: {e}")

async def doc_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """파일 감지 및 저장"""
    if update.message and update.message.document:
        doc = update.message.document
        file_name = doc.file_name
        try:
            cursor.execute("INSERT INTO file_list (name) VALUES (?)", (file_name,))
            conn.commit()
            logger.info(f"저장 성공: {file_name}")
            await update.message.reply_text(f"✅ <b>저장 성공</b>: {html.escape(file_name)}", parse_mode="HTML")
        except sqlite3.IntegrityError:
            # 중복 발생 시 알림
            await update.message.reply_text(f"⚠️ <b>파일 중복</b>: 이미 목록에 있는 파일입니다.\n이름: {html.escape(file_name)}", parse_mode="HTML")
        except Exception as e:
            logger.error(f"doc_handler 오류: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == SUPREME_ADMIN:
        await update.message.reply_text(
            f"🤖 <b>봇이 실행 중입니다</b>\n"
            f"데이터베이스: <code>{DB_FILE}</code>\n\n"
            f"<b>사용 설명:</b>\n"
            f"1. 파일을 직접 전송하거나 전달(Forward)하면 자동으로 등록됩니다.\n"
            f"2. /post 명령어로 현재 목록을 확인하고 고정할 수 있습니다.\n"
            f"3. /add [파일명] 명령어로 수동 등록이 가능합니다.",
            parse_mode="HTML"
        )

@restricted
async def cmd_add_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """수동으로 파일 이름 추가"""
    if not context.args:
        await update.message.reply_text("💡 사용 방법: /add [파일명]")
        return
    
    file_name = " ".join(context.args)
    try:
        cursor.execute("INSERT INTO file_list (name) VALUES (?)", (file_name,))
        conn.commit()
        await update.message.reply_text(f"✅ <b>수동 추가 성공</b>: {html.escape(file_name)}", parse_mode="HTML")
    except sqlite3.IntegrityError:
        # 중복 발생 시 알림
        await update.message.reply_text(f"⚠️ <b>추가 실패</b>: 이미 존재하는 파일명입니다.\n이름: {html.escape(file_name)}", parse_mode="HTML")

# --- 메인 실행 ---
if __name__ == '__main__':
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다.")
    else:
        app = Application.builder().token(TOKEN).build()

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("post", cmd_post))
        app.add_handler(CommandHandler("add", cmd_add_manual))
        app.add_handler(MessageHandler(filters.Document.ALL, doc_handler))

        logger.info("봇이 시작되었습니다.")
        app.run_polling()
