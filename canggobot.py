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
            await update.message.reply_text(f"🚫 <b>권한 없음</b>: 관리자만 사용할 수 있습니다.\n(사용자 ID: <code>{user_id}</code>)", parse_mode="HTML")
            return 
        return await func(update, context, *args, **kwargs)
    return wrapped

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """봇 생존 확인"""
    await update.message.reply_text("🏓 <b>Pong!</b> 봇이 정상적으로 연결되어 있습니다.", parse_mode="HTML")

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
    logger.info(f"메시지 수신: {update.message}")
    if update.message and update.message.document:
        doc = update.message.document
        file_name = doc.file_name
        try:
            cursor.execute("INSERT INTO file_list (name) VALUES (?)", (file_name,))
            conn.commit()
            logger.info(f"저장 성공: {file_name}")
            await update.message.reply_text(f"✅ <b>저장 성공</b>: {html.escape(file_name)}", parse_mode="HTML")
        except sqlite3.IntegrityError:
            await update.message.reply_text(f"⚠️ <b>파일 중복</b>: 이미 목록에 있는 파일입니다.\n이름: {html.escape(file_name)}", parse_mode="HTML")
        except Exception as e:
            logger.error(f"doc_handler 오류: {e}")
    else:
        logger.info("문서(Document)가 없는 메시지입니다.")

async def debug_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """모든 메시지 로그 기록 (디버깅용)"""
    user = update.effective_user
    text = update.message.text if update.message.text else "[텍스트 없음]"
    logger.info(f"디버그 - 사용자: {user.id} ({user.first_name}), 내용: {text}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == SUPREME_ADMIN:
        await update.message.reply_text(
            f"🤖 <b>봇이 정상적으로 실행 중입니다!</b>\n"
            f"데이터베이스: <code>{DB_FILE}</code>\n\n"
            f"<b>💡 사용 방법:</b>\n"
            f"1. <b>파일 등록</b>: 파일을 이 방에 새로 올리거나, <b>기존 파일을 다시 전달(Forward)</b>하면 자동으로 목록에 저장됩니다.\n"
            f"2. <b>목록 확인</b>: /list 명령어를 입력하면 현재 저장된 목록을 보여주고 고정합니다.\n"
            f"3. <b>수동 등록</b>: 파일이 너무 많다면 /add [파일명]으로 이름만 등록할 수도 있습니다.\n\n"
            f"⚠️ <i>주의: 다른 봇과 명령어가 겹치지 않도록 /post 대신 <b>/list</b>를 사용해 주세요.</i>",
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

        # 명령어 등록
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("ping", cmd_ping))  # 핑 명령어 등록
        app.add_handler(CommandHandler("list", cmd_post))
        app.add_handler(CommandHandler("add", cmd_add_manual))
        
        # 문서(파일) 핸들러
        app.add_handler(MessageHandler(filters.Document.ALL, doc_handler))
        
        # 일반 메시지 디버그 핸들러
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), debug_handler))

        logger.info("봇이 시작되었습니다.")
        app.run_polling()
