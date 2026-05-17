import os
import logging
import sqlite3
import re
import requests
from datetime import datetime
from urllib.parse import quote, urlparse, parse_qs, urlencode, urlunparse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, filters
)
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

# ========== CONFIG ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")
ALI_ID = os.getenv("ALI_ID", "Tohamy-23")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# ========== LOGGING ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== DATABASE ==========
class Database:
    def __init__(self, db_path='tracker.db'):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                platform TEXT NOT NULL,
                title TEXT,
                current_price REAL,
                target_price REAL,
                image_url TEXT,
                affiliate_url TEXT,
                currency TEXT DEFAULT 'USD',
                last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notified INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                plan TEXT DEFAULT 'free',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

    def add_product(self, user_id, url, platform, title, current_price, target_price, 
                    image_url, affiliate_url, currency='USD'):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            INSERT INTO products 
            (user_id, url, platform, title, current_price, target_price, image_url, affiliate_url, currency)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, url, platform, title, current_price, target_price, 
              image_url, affiliate_url, currency))
        conn.commit()
        conn.close()

    def get_user_products(self, user_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            SELECT id, user_id, url, platform, title, current_price, target_price, 
                   image_url, affiliate_url, currency, notified
            FROM products WHERE user_id = ? ORDER BY created_at DESC
        """, (user_id,))
        results = c.fetchall()
        conn.close()
        return results

    def get_user_product_count(self, user_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM products WHERE user_id = ?', (user_id,))
        count = c.fetchone()[0]
        conn.close()
        return count

    def get_all_active_products(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            SELECT id, user_id, url, platform, title, current_price, target_price, 
                   image_url, affiliate_url, currency, notified
            FROM products WHERE notified = 0 ORDER BY last_checked ASC
        """)
        results = c.fetchall()
        conn.close()
        return results

    def update_price(self, product_id, new_price):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            UPDATE products SET current_price = ?, last_checked = ? WHERE id = ?
        """, (new_price, datetime.now(), product_id))
        conn.commit()
        conn.close()

    def mark_notified(self, product_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('UPDATE products SET notified = 1 WHERE id = ?', (product_id,))
        conn.commit()
        conn.close()

    def delete_product(self, product_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('DELETE FROM products WHERE id = ?', (product_id,))
        conn.commit()
        conn.close()

# ========== SCRAPER ==========
class AliExpressScraper:
    def __init__(self, scraper_api_key=None):
        self.scraper_api_key = scraper_api_key
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def is_aliexpress(self, url):
        return 'aliexpress.' in url.lower() or 'a.aliexpress.' in url.lower()

    def add_affiliate(self, url, ali_id):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        for key in list(query.keys()):
            if key in ['aff_fcid', 'aff_platform', 'sk', 'aff_trace_key']:
                del query[key]
        query['aff_fcid'] = [ali_id]
        query['aff_platform'] = ['default']
        query['aff_trace_key'] = [ali_id]
        query['sk'] = ['_dSI7LJ']
        query['terminal_id'] = ['3ac645b9bf6342ee8eb9bdd1e5e4f8a2']
        new_query = urlencode(query, doseq=True)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))

    def scrape_product(self, url):
        try:
            if self.scraper_api_key:
                api_url = f"http://api.scraperapi.com?api_key={self.scraper_api_key}&url={quote(url)}&country_code=us"
                r = self.session.get(api_url, timeout=30)
                html = r.text
            else:
                r = self.session.get(url, timeout=15, headers={
                    'User-Agent': 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36',
                    'Accept-Language': 'en-US,en;q=0.9'
                })
                html = r.text

            title = "Unknown Product"
            title_patterns = [
                r'"subject":"([^"]+)"',
                r'"title":"([^"]+)"',
                r'<h1[^>]*class="product-title[^"]*"[^>]*>(.*?)</h1>',
                r'<meta property="og:title" content="([^"]+)"',
                r'"productTitle":"([^"]+)"'
            ]
            for p in title_patterns:
                m = re.search(p, html, re.S)
                if m:
                    title = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                    if len(title) > 3:
                        break

            price = None
            currency = 'USD'
            price_patterns = [
                r'"minAmount":\{"value":"([0-9.]+)"',
                r'"salePrice":\{"amount":"([0-9.]+)"',
                r'"price":"([0-9.,]+)"',
                r'"discountPrice":"([0-9.,]+)"',
                r'class="price-current"[^>]*>([0-9.,]+)',
                r'class="product-price-value"[^>]*>([0-9.,]+)',
                r'data-price="([0-9.,]+)"'
            ]
            for p in price_patterns:
                m = re.search(p, html)
                if m:
                    price_str = m.group(1).replace(',', '').replace('$', '')
                    try:
                        price = float(price_str)
                        if price > 0:
                            break
                    except:
                        continue

            image = None
            img_patterns = [
                r'"imagePath":"([^"]+)"',
                r'"imgUrl":"([^"]+)"',
                r'<meta property="og:image" content="([^"]+)"',
                r'"mainImage":"([^"]+)"'
            ]
            for p in img_patterns:
                m = re.search(p, html)
                if m:
                    image = m.group(1)
                    if image.startswith('//'):
                        image = 'https:' + image
                    break

            if 'USD' in html or '$' in html[:5000]:
                currency = 'USD'
            elif 'EUR' in html or chr(8364) in html[:5000]:
                currency = 'EUR'
            elif 'GBP' in html or chr(163) in html[:5000]:
                currency = 'GBP'

            if price and price > 0:
                return {'title': title, 'price': price, 'currency': currency, 'image': image, 'platform': 'aliexpress'}
            return None
        except Exception as e:
            logger.error(f"AliExpress scrape error: {e}")
            return None

# ========== BOT ==========
db = Database()
scraper = AliExpressScraper(SCRAPER_API_KEY)
SET_TARGET = 1

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    count = db.get_user_product_count(user_id)
    text = f"""🛒 *AliPrice Bot - AliExpress Price Tracker*

Hi {update.effective_user.first_name}!

Send me any AliExpress product link and I will track the price for you.

When the price drops to your target, I will send you an instant alert with your affiliate link!

📊 *Your Plan:* Free
🎯 *Tracked:* {count}/5 products

*Commands:*
/list - View your tracked products
/delete - Remove a product
/upgrade - Go Pro ($3/month)
/help - How to use"""
    await update.message.reply_text(text, parse_mode='Markdown')

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """📖 *How to use AliPrice Bot*

1️⃣ Open AliExpress app or website
2️⃣ Find any product you like
3️⃣ Click "Share" and copy the link
4️⃣ Paste it here!
5️⃣ Set your target price
6️⃣ Wait for the price drop alert 🔔

*Free Plan:*
• Track up to 5 products
• Check every 6 hours
• Basic alerts

*Pro Plan ($3/month):*
• Unlimited products
• Check every 30 minutes
• Instant alerts
• Price history charts

*Supported:* AliExpress only (best deals worldwide 🌍)"""
    await update.message.reply_text(text, parse_mode='Markdown')

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    user_id = update.effective_user.id

    if not scraper.is_aliexpress(url):
        await update.message.reply_text(
            "❌ Please send an AliExpress link only.\n\n"
            "Open AliExpress app → Share → Copy Link → Paste here"
        )
        return

    count = db.get_user_product_count(user_id)
    if count >= 5:
        keyboard = [[InlineKeyboardButton("🚀 Upgrade to Pro", callback_data='upgrade')]]
        await update.message.reply_text(
            "⚠️ *Free limit reached!* You have tracked 5 products.\n\n"
            "Upgrade to Pro for unlimited tracking.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return

    msg = await update.message.reply_text("🔍 Fetching product from AliExpress...")

    product = scraper.scrape_product(url)
    if not product or not product.get('price'):
        await msg.edit_text(
            "❌ Could not fetch product details. Possible reasons:\n"
            "• Product is out of stock\n"
            "• Region blocked\n"
            "• Try again in a few minutes"
        )
        return

    aff_url = scraper.add_affiliate(url, ALI_ID)

    context.user_data['pending_product'] = {
        'url': url,
        'title': product['title'],
        'price': product['price'],
        'image': product.get('image', ''),
        'currency': product.get('currency', 'USD'),
        'affiliate_url': aff_url
    }

    price_text = f"{product['currency']} {product['price']:.2f}"
    keyboard = [
        [InlineKeyboardButton("🎯 Track Price Drop", callback_data='track')],
        [InlineKeyboardButton("🛒 Buy Now", url=aff_url)],
    ]
    caption = f"""📦 *{product['title'][:200]}*

💵 *Current Price:* `{price_text}`
🏪 *Store:* AliExpress

Click *Track* to set a target price and get notified when it drops!"""

    if product.get('image'):
        await msg.delete()
        await update.message.reply_photo(
            photo=product['image'],
            caption=caption,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    else:
        await msg.edit_text(
            caption,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

async def track_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    pending = context.user_data.get('pending_product')
    if not pending:
        await query.edit_message_text("Session expired. Please send the link again.")
        return

    price_text = f"{pending['currency']} {pending['price']:.2f}"
    await query.edit_message_text(
        f"💡 *Current price is* `{price_text}`\n\n"
        f"Reply with your target price (e.g., `15.99`) and I will alert you when it drops!\n\n"
        f"_Tip: Set it 10-20% below current price for best results._",
        parse_mode='Markdown'
    )
    return SET_TARGET

async def receive_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        target = float(update.message.text.strip())
        if target <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid positive number (e.g., 19.99)")
        return SET_TARGET

    pending = context.user_data.get('pending_product')
    if not pending:
        await update.message.reply_text("Session expired. Send the link again.")
        return ConversationHandler.END

    user_id = update.effective_user.id
    db.add_product(
        user_id=user_id,
        url=pending['url'],
        platform='aliexpress',
        title=pending['title'],
        current_price=pending['price'],
        target_price=target,
        image_url=pending.get('image', ''),
        affiliate_url=pending['affiliate_url'],
        currency=pending.get('currency', 'USD')
    )

    del context.user_data['pending_product']

    price_text = f"{pending['currency']} {pending['price']:.2f}"
    target_text = f"{pending['currency']} {target:.2f}"

    await update.message.reply_text(
        f"✅ *Tracking Started!*\n\n"
        f"📦 {pending['title'][:80]}...\n"
        f"💵 Current: `{price_text}`\n"
        f"🎯 Target: `{target_text}`\n\n"
        f"⏰ I check prices every 6 hours.\n"
        f"🔔 You will get an instant alert when the price drops!\n\n"
        f"Use /list to see all your tracked products.",
        parse_mode='Markdown'
    )
    return ConversationHandler.END

async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    products = db.get_user_products(user_id)

    if not products:
        await update.message.reply_text(
            "📭 You are not tracking any products yet.\n\n"
            "Send me an AliExpress link to start tracking!"
        )
        return

    text = "📊 *Your AliExpress Tracked Products*\n\n"
    keyboard = []

    for p in products:
        pid, _, _, platform, title, current, target, _, _, currency, _ = p
        status = "🟢" if current <= target else "🔴"
        text += f"{status} *{title[:40]}...*\n"
        text += f"   💵 `{currency} {current:.2f}` → 🎯 `{currency} {target:.2f}`\n\n"
        keyboard.append([InlineKeyboardButton(f"🗑 Delete #{pid}", callback_data=f'del_{pid}')])

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith('del_'):
        pid = int(data.split('_')[1])
        db.delete_product(pid)
        await query.edit_message_text("✅ Product removed from tracking.")

async def upgrade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("💳 Pay with Stripe", url="https://your-stripe-link.com")],
        [InlineKeyboardButton("💰 Pay with Crypto", url="https://your-crypto-link.com")],
        [InlineKeyboardButton("📩 Contact Admin", url=f"tg://user?id={ADMIN_ID}")]
    ]
    text = """🚀 *Upgrade to Pro*

*Free Plan:*
• 5 products max
• Check every 6 hours
• Basic alerts

*Pro Plan - $3/month:*
• Unlimited products
• Check every 30 minutes
• Instant Telegram alerts
• Price history charts
• Priority support

Click below to upgrade:"""
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'pending_product' in context.user_data:
        del context.user_data['pending_product']
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

def check_prices_job():
    logger.info("Running AliExpress price check...")
    products = db.get_all_active_products()

    for p in products:
        pid, user_id, url, platform, title, old_price, target, image, aff_url, currency, notified = p
        try:
            product = scraper.scrape_product(url)
            if not product or not product.get('price'):
                continue

            new_price = product['price']
            db.update_price(pid, new_price)

            if new_price <= target and not notified:
                old_text = f"{currency} {old_price:.2f}"
                new_text = f"{currency} {new_price:.2f}"
                alert_text = (
                    f"🎉 *PRICE DROP ALERT!*\n\n"
                    f"📦 {title[:100]}\n\n"
                    f"💵 Old: `{old_text}`\n"
                    f"🔥 New: `{new_text}`\n"
                    f"🎯 Target: `{currency} {target:.2f}`\n\n"
                    f"✅ Price dropped to your target! Grab it now!"
                )
                keyboard = [[InlineKeyboardButton("🛒 Buy Now on AliExpress", url=aff_url)]]
                logger.info(f"ALERT: User {user_id} - {title} dropped to {new_price}")
                db.mark_notified(pid)
        except Exception as e:
            logger.error(f"Error checking product {pid}: {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(check_prices_job, IntervalTrigger(hours=6))
scheduler.start()

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    track_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(track_callback, pattern='^track$')],
        states={
            SET_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_target)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("list", list_products))
    application.add_handler(CommandHandler("upgrade", upgrade_cmd))
    application.add_handler(track_conv)
    application.add_handler(CallbackQueryHandler(delete_callback, pattern='^del_'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    logger.info("AliPrice Bot started!")
    application.run_polling()

if __name__ == '__main__':
    main()
