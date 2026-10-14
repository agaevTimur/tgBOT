import asyncio
import io
import logging
import os
import re
import warnings

from PIL import Image
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.warnings import PTBUserWarning
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("pdfbot")
# Buttons are tracked per chat, not per message, which is what we want here.
warnings.filterwarnings("ignore", message=".*per_message=False.*", category=PTBUserWarning)

COLLECTING, ASK_NAME = range(2)
MAX_PHOTOS = 100

DONE_KEYBOARD = InlineKeyboardMarkup(
    [[
        InlineKeyboardButton("✅ Yes, that's all", callback_data="done"),
        InlineKeyboardButton("➕ Add more", callback_data="more"),
    ]]
)


# ---------- PDF logic (no Telegram dependency, easy to test) ----------

def images_to_pdf(images: list[bytes]) -> bytes:
    """Combine raw image bytes into a single PDF, one image per page."""
    if not images:
        raise ValueError("no images given")
    pages = []
    for raw in images:
        img = Image.open(io.BytesIO(raw))
        img.load()
        # PDF pages need RGB; flatten transparency onto white.
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, "white")
            bg.paste(img, mask=img.getchannel("A"))
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        pages.append(img)
    out = io.BytesIO()
    pages[0].save(out, format="PDF", save_all=True, append_images=pages[1:], resolution=100.0)
    return out.getvalue()


def safe_filename(name: str) -> str:
    """Turn user text into a safe file name ending in .pdf."""
    name = name.strip()
    if name.lower().endswith(".pdf"):
        name = name[:-4]
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .")
    name = name[:100] or "photos"
    return f"{name}.pdf"


# ---------- Telegram handlers ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["photos"] = []
    await update.message.reply_text(
        "Hi! Send me photos and I'll turn them into a PDF.\n"
        "Send /cancel at any time to start over."
    )
    return COLLECTING


async def receive_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    photos = context.user_data.setdefault("photos", [])

    if len(photos) >= MAX_PHOTOS:
        await msg.reply_text(f"That's the limit of {MAX_PHOTOS} photos. Is that all?", reply_markup=DONE_KEYBOARD)
        return COLLECTING

    if msg.photo:
        file = await msg.photo[-1].get_file()  # largest size
    else:  # image sent as a file, keeps full quality
        file = await msg.document.get_file()
    photos.append(bytes(await file.download_as_bytearray()))

    # Remove the previous "Is that all?" prompt so albums don't spam the chat.
    old_prompt = context.user_data.pop("prompt_id", None)
    if old_prompt:
        try:
            await context.bot.delete_message(msg.chat_id, old_prompt)
        except Exception:
            pass

    prompt = await msg.reply_text(
        f"Got it, {len(photos)} photo(s) so far. Is that all?",
        reply_markup=DONE_KEYBOARD,
    )
    context.user_data["prompt_id"] = prompt.message_id
    return COLLECTING


async def done_or_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.pop("prompt_id", None)

    if query.data == "more":
        await query.edit_message_text("OK, send more photos.")
        return COLLECTING

    if not context.user_data.get("photos"):
        await query.edit_message_text("You haven't sent any photos yet. Send one first.")
        return COLLECTING

    await query.edit_message_text("What would you like to name the PDF?")
    return ASK_NAME


async def text_while_collecting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Let users type 'yes' / 'all' / 'done' instead of tapping the button."""
    text = update.message.text.strip().lower()
    if text in {"yes", "y", "done", "all", "that's all", "thats all", "yes its all", "yes it's all"}:
        if not context.user_data.get("photos"):
            await update.message.reply_text("Send me a photo first.")
            return COLLECTING
        await update.message.reply_text("What would you like to name the PDF?")
        return ASK_NAME
    await update.message.reply_text("Send me a photo, or tap \"Yes, that's all\" when you're done.")
    return COLLECTING


async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    filename = safe_filename(update.message.text)
    photos = context.user_data.get("photos", [])
    await update.message.reply_text(f"Making {filename} from {len(photos)} photo(s)...")

    try:
        pdf = images_to_pdf(photos)
    except Exception:
        log.exception("PDF build failed")
        await update.message.reply_text("Sorry, I couldn't build the PDF. Send /start to try again.")
        context.user_data.clear()
        return ConversationHandler.END

    await update.message.reply_document(document=io.BytesIO(pdf), filename=filename)
    context.user_data.clear()
    await update.message.reply_text("Done! Send more photos any time to make another PDF.")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("Cancelled. Send a photo whenever you want to start again.")
    return ConversationHandler.END


def main() -> None:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("Set the BOT_TOKEN environment variable to your bot token from @BotFather.")

    image = filters.PHOTO | filters.Document.IMAGE
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start), MessageHandler(image, receive_photo)],
        states={
            COLLECTING: [
                MessageHandler(image, receive_photo),
                CallbackQueryHandler(done_or_more, pattern="^(done|more)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, text_while_collecting),
            ],
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_name)],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("start", start)],
    )

    app = Application.builder().token(token).build()
    app.add_handler(conv)
    log.info("Bot is running. Press Ctrl+C to stop.")
    asyncio.set_event_loop(asyncio.new_event_loop())
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
