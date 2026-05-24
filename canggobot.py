import os
import sqlite3
import html
import logging
from functools import wraps
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
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

# 연결할 채팅방 정보
TARGET_CHAT_ID = -1002128096945  # https://t.me/c/2128096945
TARGET_CHAT_LINK_ID = "2128096945"

# 카테고리별 고정 링크 데이터
CATEGORY_DATA = {
    "BL": {"완결": "50506", "미완": "51228"},
    "로판": {"완결": "31034", "미완": "50590"},
    "로맨스": {"완결": "31028", "미완": "50579"},
    "판타지": {"완결": "31038", "미완": "51541"},
    "무협": {"완결": "50659", "미완": "50716"},
}

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
# 스키마 확장: category, status 추가
cursor.execute("""
    CREATE TABLE IF NOT EXISTS file_list (
        name TEXT PRIMARY KEY, 
        message_id INTEGER,
        category TEXT,
        status TEXT
    )
""")
# 기존 테이블에 컬럼이 없는 경우 추가
for col, col_type in [("message_id", "INTEGER"), ("category", "TEXT"), ("status", "TEXT")]:
    try:
        cursor.execute(f"ALTER TABLE file_list ADD COLUMN {col} {col_type}")
    except sqlite3.OperationalError:
        pass
conn.commit()

# --- 공통 UI 구성 ---
def get_main_menu_keyboard():
    """하단 고정 메뉴 (ReplyKeyboardMarkup)"""
    keyboard = [
        ["BL", "로판"],
        ["로맨스", "판타지", "무협"],
        ["전체 목록 확인 📋"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, persistent=True)

# --- 보안 데코레이터 ---
def restricted(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != SUPREME_ADMIN:
            logger.warning(f"Unauthorized access attempt by ID: {user_id}")
            if update.effective_chat.type == "private":
                await update.message.reply_text(f"🚫 <b>권한 없음</b>: 관리자만 사용할 수 있습니다.", parse_mode="HTML")
            return 
        return await func(update, context, *args, **kwargs)
    return wrapped

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """봇 시작 및 메인 메뉴 표시"""
    if update.effective_user.id == SUPREME_ADMIN:
        await update.message.reply_text(
            "🤖 <b>파일 관리 봇 메인 메뉴</b>\n\n"
            "아래 메뉴를 클릭하여 각 카테고리의 완결/미완 목록으로 이동하거나 전체 목록을 확인할 수 있습니다.",
            reply_markup=get_main_menu_keyboard(),
            parse_mode="HTML"
        )

async def category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """카테고리 버튼 클릭 시 완결/미완 링크 제공"""
    category = update.message.text
    if category in CATEGORY_DATA:
        links = CATEGORY_DATA[category]
        complete_url = f"https://t.me/c/{TARGET_CHAT_LINK_ID}/{links['완결']}"
        incomplete_url = f"https://t.me/c/{TARGET_CHAT_LINK_ID}/{links['미완']}"
        
        keyboard = [
            [
                InlineKeyboardButton("🏆 완결 바로가기", url=complete_url),
                InlineKeyboardButton("⏳ 미완 바로가기", url=incomplete_url)
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"📂 <b>{category}</b> 카테고리입니다.\n"
            f"원하시는 목록의 바로가기 버튼을 클릭하세요.",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    elif category == "전체 목록 확인 📋":
        await cmd_post(update, context)

# --- 기존 핸들러 ---
@restricted
async def cmd_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """전체 목록 조회"""
    try:
        cursor.execute("SELECT name, message_id FROM file_list")
        rows = cursor.fetchall()
        
        if not rows:
            await update.message.reply_text("📄 등록된 파일이 없습니다.", reply_markup=get_main_menu_keyboard())
            return
        
        file_links = []
        for name, msg_id in rows:
            escaped_name = html.escape(name)
            if msg_id:
                link = f"https://t.me/c/{TARGET_CHAT_LINK_ID}/{msg_id}"
                file_links.append(f"• <a href=\"{link}\">{escaped_name}</a>")
            else:
                file_links.append(f"• {escaped_name}")

        msg_text = f"📄 <b>현재 전체 파일 목록</b>:\n\n" + "\n".join(file_links)
        
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text=msg_text, 
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=get_main_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"cmd_post 오류: {e}")

async def doc_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """파일 감지 및 저장"""
    chat_id = update.effective_chat.id
    if chat_id != TARGET_CHAT_ID:
        return

    if update.message and update.message.document:
        doc = update.message.document
        file_name = doc.file_name
        msg_id = update.message.message_id
        
        try:
            cursor.execute("INSERT INTO file_list (name, message_id) VALUES (?, ?)", (file_name, msg_id))
            conn.commit()
            await update.message.reply_text(f"✅ <b>저장 성공</b>: {html.escape(file_name)}", parse_mode="HTML")
        except sqlite3.IntegrityError:
            cursor.execute("UPDATE file_list SET message_id = ? WHERE name = ?", (msg_id, file_name))
            conn.commit()
            await update.message.reply_text(f"⚠️ <b>링크 갱신</b>: {html.escape(file_name)}", parse_mode="HTML")
        except Exception as e:
            logger.error(f"doc_handler 오류: {e}")

# --- 메인 실행 ---
if __name__ == '__main__':
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN이 설정되지 않았습니다.")
    else:
        app = Application.builder().token(TOKEN).build()

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("list", cmd_post))
        
        # 메인 메뉴 카테고리 처리
        category_filter = filters.Text(["BL", "로판", "로맨스", "판타지", "무협", "전체 목록 확인 📋"])
        app.add_handler(MessageHandler(category_filter, category_handler))
        
        # 파일 감지
        app.add_handler(MessageHandler(filters.Document.ALL, doc_handler))

        logger.info("봇이 시작되었습니다.")
        app.run_polling()"}]}
