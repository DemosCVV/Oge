import aiosqlite
from typing import Optional, Tuple, List, Dict

DB_PATH = "bot.sqlite3"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at INTEGER
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            k TEXT PRIMARY KEY,
            v TEXT
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS balances (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 0
        );
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_slug TEXT NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT NOT NULL, -- pending/approved/denied
            receipt_file_id TEXT,
            receipt_file_unique_id TEXT,
            receipt_count INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER,
            updated_at INTEGER
        );
        """)
        # Антифрод: запрет повторного использования одного и того же file_unique_id
        await db.execute("""
        CREATE TABLE IF NOT EXISTS used_receipts (
            receipt_unique_id TEXT PRIMARY KEY,
            purchase_id INTEGER,
            user_id INTEGER,
            created_at INTEGER
        );
        """)
        await db.commit()

async def upsert_user(user_id: int, username: Optional[str], first_name: Optional[str], ts: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT INTO users(user_id, username, first_name, created_at)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
          username=excluded.username,
          first_name=excluded.first_name;
        """, (user_id, username or "", first_name or "", ts))
        await db.commit()

async def get_users_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users;") as cur:
            row = await cur.fetchone()
            return int(row[0])

async def get_all_user_ids() -> List[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users;") as cur:
            rows = await cur.fetchall()
            return [int(r[0]) for r in rows]

async def get_setting(k: str, default: str = "") -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT v FROM settings WHERE k=?;", (k,)) as cur:
            row = await cur.fetchone()
            if not row:
                return default
            return row[0] or default

async def set_setting(k: str, v: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT INTO settings(k, v) VALUES(?, ?)
        ON CONFLICT(k) DO UPDATE SET v=excluded.v;
        """, (k, v))
        await db.commit()

async def ensure_default_card():
    card = await get_setting("card_number", "")
    owner = await get_setting("card_owner", "")
    if not card:
        await set_setting("card_number", "0000 0000 0000 0000")
    if not owner:
        await set_setting("card_owner", "ИМЯ ФАМИЛИЯ")

async def get_card() -> Tuple[str, str]:
    card = await get_setting("card_number", "0000 0000 0000 0000")
    owner = await get_setting("card_owner", "ИМЯ ФАМИЛИЯ")
    return card, owner

async def add_balance(user_id: int, delta: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT INTO balances(user_id, balance) VALUES(?, ?)
        ON CONFLICT(user_id) DO UPDATE SET balance=balance+excluded.balance;
        """, (user_id, delta))
        await db.commit()
        async with db.execute("SELECT balance FROM balances WHERE user_id=?;", (user_id,)) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0

async def has_pending_purchase(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
        SELECT 1 FROM purchases
        WHERE user_id=? AND status='pending'
        ORDER BY id DESC LIMIT 1;
        """, (user_id,)) as cur:
            row = await cur.fetchone()
            return row is not None

async def create_purchase(user_id: int, product_slug: str, amount: int, ts: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
        INSERT INTO purchases(user_id, product_slug, amount, status, created_at, updated_at)
        VALUES(?, ?, ?, 'pending', ?, ?);
        """, (user_id, product_slug, amount, ts, ts))
        await db.commit()
        return int(cur.lastrowid)

async def get_purchase(purchase_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
        SELECT id, user_id, product_slug, amount, status,
               receipt_file_id, receipt_file_unique_id, receipt_count
        FROM purchases WHERE id=?;
        """, (purchase_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return {
                "id": int(row[0]),
                "user_id": int(row[1]),
                "product_slug": row[2],
                "amount": int(row[3]),
                "status": row[4],
                "receipt_file_id": row[5],
                "receipt_file_unique_id": row[6],
                "receipt_count": int(row[7]),
            }

async def set_purchase_status(purchase_id: int, status: str, ts: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE purchases SET status=?, updated_at=? WHERE id=?;", (status, ts, purchase_id))
        await db.commit()

async def attach_receipt(purchase_id: int, receipt_file_id: str, receipt_unique_id: str, ts: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        UPDATE purchases
        SET receipt_file_id=?, receipt_file_unique_id=?, receipt_count=receipt_count+1, updated_at=?
        WHERE id=?;
        """, (receipt_file_id, receipt_unique_id, ts, purchase_id))
        await db.commit()

async def get_latest_pending_purchase(user_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
        SELECT id, product_slug, amount, status, receipt_file_id, receipt_file_unique_id, receipt_count
        FROM purchases
        WHERE user_id=? AND status='pending'
        ORDER BY id DESC LIMIT 1;
        """, (user_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return {
                "id": int(row[0]),
                "product_slug": row[1],
                "amount": int(row[2]),
                "status": row[3],
                "receipt_file_id": row[4],
                "receipt_file_unique_id": row[5],
                "receipt_count": int(row[6]),
            }

async def receipt_is_used(receipt_unique_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM used_receipts WHERE receipt_unique_id=? LIMIT 1;", (receipt_unique_id,)) as cur:
            return (await cur.fetchone()) is not None

async def mark_receipt_used(receipt_unique_id: str, purchase_id: int, user_id: int, ts: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT OR IGNORE INTO used_receipts(receipt_unique_id, purchase_id, user_id, created_at)
        VALUES(?, ?, ?, ?);
        """, (receipt_unique_id, purchase_id, user_id, ts))
        await db.commit()

async def get_stats() -> Dict[str, int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM purchases;") as cur:
            purchases_total = int((await cur.fetchone())[0])
        async with db.execute("SELECT COUNT(*) FROM purchases WHERE status='approved';") as cur:
            approved = int((await cur.fetchone())[0])
        async with db.execute("SELECT COUNT(*) FROM purchases WHERE status='pending';") as cur:
            pending = int((await cur.fetchone())[0])
        # cancelled считаем как denied в общей статистике
        async with db.execute("SELECT COUNT(*) FROM purchases WHERE status IN ('denied','canceled');") as cur:
            denied = int((await cur.fetchone())[0])
        async with db.execute("SELECT COALESCE(SUM(amount),0) FROM purchases WHERE status='approved';") as cur:
            revenue = int((await cur.fetchone())[0])
        return {
            "purchases_total": purchases_total,
            "approved": approved,
            "pending": pending,
            "denied": denied,
            "revenue": revenue,
        }

async def find_user_id_by_username(username: str) -> Optional[int]:
    username = username.lstrip("@").strip().lower()
    if not username:
        return None
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE lower(username)=? LIMIT 1;", (username,)) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else None
