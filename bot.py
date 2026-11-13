"""Telegram bot: send a logo -> pick an animation -> get a .tgs custom emoji."""
import asyncio
import logging
import os
import tempfile

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, InputSticker,
                      Update)
from telegram.constants import StickerFormat, StickerType
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

from tgs_maker import ANIMATIONS, make_tgs

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_EXT = (".svg", ".png", ".jpg", ".jpeg", ".webp")


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send me a logo (SVG is best, or PNG/JPG sent as a *file*) and pick an "
        "animation. I'll give you a .tgs sticker and can add it to your own "
        "custom emoji pack.",
        parse_mode="Markdown",
    )


async def on_logo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.photo:
        tg_file = await msg.photo[-1].get_file()
        ext = ".jpg"
    else:
        doc = msg.document
        ext = os.path.splitext(doc.file_name or "")[1].lower()
        if ext not in ALLOWED_EXT:
            await msg.reply_text("Please send an SVG, PNG or JPG file.")
            return
        tg_file = await doc.get_file()

    path = os.path.join(tempfile.mkdtemp(prefix="logo_"), "logo" + ext)
    await tg_file.download_to_drive(path)
    ctx.user_data["logo"] = path

    names = list(ANIMATIONS.items())
    rows = [[InlineKeyboardButton(label, callback_data=f"anim:{key}")
             for key, (label, _) in names[i:i + 2]]
            for i in range(0, len(names), 2)]
    await msg.reply_text("Pick an animation:", reply_markup=InlineKeyboardMarkup(rows))


async def on_animation(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    key = q.data.split(":", 1)[1]
    logo = ctx.user_data.get("logo")
    if not logo or not os.path.exists(logo):
        await q.message.reply_text("Send me a logo first.")
        return

    await q.message.reply_text("Building… ⏳")
    out = os.path.join(os.path.dirname(logo), f"{key}.tgs")
    try:
        await asyncio.to_thread(make_tgs, logo, key, out)
    except Exception as e:  # noqa: BLE001
        logging.exception("generation failed")
        await q.message.reply_text(f"❌ {e}")
        return

    ctx.user_data["tgs"] = out
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ Add to my emoji pack", callback_data="pack")]])
    with open(out, "rb") as f:
        await q.message.reply_document(f, filename=f"{key}.tgs",
                                       caption=f"{os.path.getsize(out) / 1024:.1f} KB", reply_markup=kb)


async def on_pack(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    tgs = ctx.user_data.get("tgs")
    if not tgs or not os.path.exists(tgs):
        await q.message.reply_text("Generate an animation first.")
        return

    user_id = q.from_user.id
    bot_name = (await ctx.bot.get_me()).username
    set_name = f"emoji_{user_id}_by_{bot_name}"

    def sticker():
        return InputSticker(open(tgs, "rb"), ["✨"], StickerFormat.ANIMATED)

    try:
        try:
            await ctx.bot.add_sticker_to_set(user_id, set_name, sticker())
        except Exception:  # set doesn't exist yet -> create it
            await ctx.bot.create_new_sticker_set(
                user_id, set_name, "My Animated Emoji", [sticker()],
                sticker_type=StickerType.CUSTOM_EMOJI)
        await q.message.reply_text(f"✅ Added!\nhttps://t.me/addemoji/{set_name}")
    except Exception as e:  # noqa: BLE001
        logging.exception("pack failed")
        await q.message.reply_text(f"❌ Couldn't add to pack: {e}")


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, on_logo))
    app.add_handler(CallbackQueryHandler(on_animation, pattern=r"^anim:"))
    app.add_handler(CallbackQueryHandler(on_pack, pattern=r"^pack$"))

    # On Render (or any host that gives a public URL) use webhook mode so the
    # free instance can sleep and wake up when Telegram sends a message.
    base_url = os.environ.get("WEBHOOK_URL") or os.environ.get("RENDER_EXTERNAL_URL")
    if base_url:
        port = int(os.environ.get("PORT", "10000"))
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=TOKEN,
            webhook_url=f"{base_url.rstrip('/')}/{TOKEN}",
            drop_pending_updates=True,
        )
    else:
        app.run_polling()


if __name__ == "__main__":
    main()
