import sqlite3
from datetime import datetime

class Database:
    def __init__(self, db_path='ali_tracker.db'):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute('''
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
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                plan TEXT DEFAULT 'free',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.commit()
        conn.close()

    def add_product(self, user_id, url, platform, title, current_price, target_price, 
                    image_url, affiliate_url, currency='USD'):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute('''
            INSERT INTO products 
            (user_id, url, platform, title, current_price, target_price, image_url, affiliate_url, currency)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, url, platform, title, current_price, target_price, 
              image_url, affiliate_url, currency))

        conn.commit()
        conn.close()

    def get_user_products(self, user_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute('''
            SELECT id, user_id, url, platform, title, current_price, target_price, 
                   image_url, affiliate_url, currency, notified
            FROM products 
            WHERE user_id = ? 
            ORDER BY created_at DESC
        ''', (user_id,))

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

        c.execute('''
            SELECT id, user_id, url, platform, title, current_price, target_price, 
                   image_url, affiliate_url, currency, notified
            FROM products 
            WHERE notified = 0
            ORDER BY last_checked ASC
        ''')

        results = c.fetchall()
        conn.close()
        return results

    def update_price(self, product_id, new_price):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute('''
            UPDATE products 
            SET current_price = ?, last_checked = ? 
            WHERE id = ?
        ''', (new_price, datetime.now(), product_id))

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
