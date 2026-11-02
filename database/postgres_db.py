import json
import logging
from datetime import datetime, timedelta

import asyncpg

import config
from config import DATABASE_URL

logger = logging.getLogger(__name__)
_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set")
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            ssl="require",
            statement_cache_size=0,
            min_size=1,
            max_size=5,
            timeout=30,
        )
        logger.info("DB pool created")
    return _pool


async def init_db():
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not set - DB init skipped")
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        # ==== users (расширяем существующую) ====
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                lang TEXT DEFAULT 'ru',
                is_banned BOOLEAN DEFAULT FALSE,
                is_paid BOOLEAN DEFAULT FALSE,
                subscription_end DATE,
                trial_used BOOLEAN DEFAULT FALSE,
                trial_used_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                last_seen TIMESTAMPTZ DEFAULT NOW()
            );

            ALTER TABLE users ADD COLUMN IF NOT EXISTS is_paid BOOLEAN DEFAULT FALSE;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_end DATE;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_used BOOLEAN DEFAULT FALSE;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_used_at TIMESTAMPTZ;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS lang TEXT DEFAULT 'ru';
            ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN DEFAULT FALSE;

            ALTER TABLE settings ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
        """)

        # ==== admins ====
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY,
                added_by BIGINT,
                added_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        # ==== settings (key-value JSON) ====
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        # ==== payments ====
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                stars_paid INTEGER NOT NULL DEFAULT 0,
                days INTEGER NOT NULL DEFAULT 0,
                payment_id TEXT UNIQUE,
                source TEXT DEFAULT 'stars',
                added_by BIGINT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);
        """)

        # ==== track_cache (уже был, проверим) ====
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS track_cache (
                url_hash TEXT PRIMARY KEY,
                original_url TEXT,
                platform TEXT,
                title TEXT,
                performer TEXT,
                duration INTEGER,
                file_id TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                hits INTEGER DEFAULT 0
            );
        """)

        # ==== download_usage (счётчик скачиваний в день) ====
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS download_usage (
                user_id BIGINT NOT NULL,
                usage_date DATE NOT NULL,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, usage_date)
            );
        """)

        # ==== ads ====
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ads (
                id SERIAL PRIMARY KEY,
                text TEXT NOT NULL,
                link TEXT,
                button_text TEXT DEFAULT 'Подробнее',
                link_mode TEXT DEFAULT 'direct',
                utm_source TEXT DEFAULT 'music_bot',
                utm_medium TEXT DEFAULT 'ad',
                weight INTEGER DEFAULT 1,
                enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            ALTER TABLE ads ADD COLUMN IF NOT EXISTS link_mode TEXT DEFAULT 'direct';
        """)

        # ==== ad_stats ====
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ad_stats (
                id SERIAL PRIMARY KEY,
                ad_id INTEGER REFERENCES ads(id) ON DELETE CASCADE,
                user_id BIGINT,
                action TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_ad_stats_ad ON ad_stats(ad_id);
            CREATE INDEX IF NOT EXISTS idx_ad_stats_date ON ad_stats(created_at);
        """)

        # ==== seed settings ====
        for key, default in [
            ("pricing", config.DEFAULT_PRICING),
            ("trial", config.DEFAULT_TRIAL),
            ("ads_config", config.DEFAULT_ADS_CONFIG),
            ("download_limits", config.DEFAULT_DOWNLOAD_LIMITS),
            ("action_prices", config.DEFAULT_ACTION_PRICES),
            ("billing_mode", config.DEFAULT_BILLING_MODE),
        ]:
            exists = await conn.fetchval("SELECT 1 FROM settings WHERE key=$1", key)
            if not exists:
                await conn.execute(
                    "INSERT INTO settings (key, value) VALUES ($1, $2)",
                    key, json.dumps(default, ensure_ascii=False),
                )
        # ==== one_time_features ====
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS one_time_features (
                id SERIAL PRIMARY KEY,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                price_stars INTEGER DEFAULT 0,
                uses_limit INTEGER DEFAULT 1,
                enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        # ==== user_features ====
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_features (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                feature_id INTEGER REFERENCES one_time_features(id) ON DELETE CASCADE,
                uses_left INTEGER DEFAULT 0,
                expires_at TIMESTAMPTZ,
                given_by BIGINT,
                given_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_user_features_user ON user_features(user_id);
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_balances (
                user_id BIGINT PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount INTEGER NOT NULL,
                kind TEXT NOT NULL,
                action TEXT,
                note TEXT,
                created_by BIGINT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id);
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_counters (
                user_id BIGINT NOT NULL,
                usage_date DATE NOT NULL,
                action TEXT NOT NULL,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, usage_date, action)
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS withdrawals (
                id SERIAL PRIMARY KEY,
                amount INTEGER NOT NULL,
                note TEXT,
                created_by BIGINT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS downloads_history (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                url TEXT,
                title TEXT,
                performer TEXT,
                platform TEXT,
                file_id TEXT,
                downloaded_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_dl_history_user ON downloads_history(user_id);
        """)
    logger.info("DB schema ready")


# ============================================================
# USERS
# ============================================================

async def get_user(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)
        return dict(row) if row else None


async def upsert_user(user_id: int, username: str, first_name: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (user_id, username, first_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE
            SET username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                last_seen = NOW()
        """, user_id, username, first_name)


async def set_ban(user_id: int, banned: bool):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_banned=$1 WHERE user_id=$2", banned, user_id)


# ============================================================
# SETTINGS
# ============================================================

async def get_setting(key: str, default=None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval("SELECT value FROM settings WHERE key=$1", key)
    if val is None:
        return default
    try:
        return json.loads(val)
    except Exception:
        return val


async def set_setting(key: str, value):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO settings (key, value, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()
        """, key, json.dumps(value, ensure_ascii=False))


# ============================================================
# SUBSCRIPTION / TRIAL
# ============================================================

async def is_paid(user_id: int) -> bool:
    if config.FREE_MODE:
        return True
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT is_paid, subscription_end FROM users WHERE user_id=$1", user_id
        )
    if not row:
        return False
    if not row["is_paid"]:
        return False
    if row["subscription_end"] and row["subscription_end"] >= datetime.now().date():
        return True
    # просрочен — снимем флаг
    if row["subscription_end"]:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET is_paid=FALSE WHERE user_id=$1", user_id
            )
    return False


async def set_subscription(user_id: int, days: int, stars_paid: int = 0, source: str = "manual", added_by: int | None = None):
    end = (datetime.now() + timedelta(days=days)).date()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE users SET is_paid=TRUE, subscription_end=$2 WHERE user_id=$1
        """, user_id, end)
        await conn.execute("""
            INSERT INTO payments (user_id, stars_paid, days, source, added_by)
            VALUES ($1, $2, $3, $4, $5)
        """, user_id, stars_paid, days, source, added_by)


async def get_trial() -> dict:
    data = await get_setting("trial", config.DEFAULT_TRIAL)
    if not isinstance(data, dict):
        return config.DEFAULT_TRIAL
    return {**config.DEFAULT_TRIAL, **data}


async def set_trial(enabled: bool, days: int):
    await set_setting("trial", {"enabled": enabled, "days": days})


async def has_trial_used(user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT trial_used FROM users WHERE user_id=$1", user_id)
    return bool(row and row["trial_used"])


async def activate_trial(user_id: int) -> bool:
    """Активирует триал. Возвращает True если удалось."""
    trial = await get_trial()
    if not trial.get("enabled"):
        return False
    if await has_trial_used(user_id):
        return False
    days = int(trial.get("days", 0))
    if days <= 0:
        return False
    end = (datetime.now() + timedelta(days=days)).date()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE users
            SET trial_used=TRUE, trial_used_at=NOW(),
                is_paid=TRUE, subscription_end=$2
            WHERE user_id=$1
        """, user_id, end)
    return True


async def reset_all_trials():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET trial_used=FALSE, trial_used_at=NULL")


async def count_trial_used() -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM users WHERE trial_used=TRUE") or 0


# ============================================================
# PRICING
# ============================================================

async def get_pricing() -> dict:
    data = await get_setting("pricing", config.DEFAULT_PRICING)
    if not isinstance(data, dict):
        return config.DEFAULT_PRICING
    return data


async def set_pricing(pricing: dict):
    await set_setting("pricing", pricing)


# ============================================================
# DOWNLOAD LIMITS
# ============================================================

async def get_download_limits() -> dict:
    data = await get_setting("download_limits", config.DEFAULT_DOWNLOAD_LIMITS)
    if not isinstance(data, dict):
        return config.DEFAULT_DOWNLOAD_LIMITS
    return {**config.DEFAULT_DOWNLOAD_LIMITS, **data}


async def set_download_limits(free: int, paid: int):
    await set_setting("download_limits", {"free": free, "paid": paid})


async def get_downloads_today(user_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval("""
            SELECT count FROM download_usage WHERE user_id=$1 AND usage_date=CURRENT_DATE
        """, user_id)
    return int(val or 0)


async def increment_download(user_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO download_usage (user_id, usage_date, count)
            VALUES ($1, CURRENT_DATE, 1)
            ON CONFLICT (user_id, usage_date) DO UPDATE
            SET count = download_usage.count + 1
        """, user_id)
        val = await conn.fetchval("""
            SELECT count FROM download_usage WHERE user_id=$1 AND usage_date=CURRENT_DATE
        """, user_id)
    return int(val or 0)


async def can_download(user_id: int) -> tuple[bool, int, int]:
    """Возвращает (можно?, использовано, лимит). Лимит -1 = без ограничений."""
    limits = await get_download_limits()
    paid = await is_paid(user_id)
    limit = int(limits["paid"] if paid else limits["free"])
    if limit < 0:
        return (True, 0, -1)
    used = await get_downloads_today(user_id)
    return (used < limit, used, limit)


# ============================================================
# ADS
# ============================================================

async def get_ads_config() -> dict:
    data = await get_setting("ads_config", config.DEFAULT_ADS_CONFIG)
    if not isinstance(data, dict):
        return config.DEFAULT_ADS_CONFIG
    return {**config.DEFAULT_ADS_CONFIG, **data}


async def set_ads_config(**kwargs):
    current = await get_ads_config()
    for k, v in kwargs.items():
        current[k] = v
    await set_setting("ads_config", current)


async def get_all_ads(only_enabled: bool = False) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if only_enabled:
            rows = await conn.fetch("SELECT * FROM ads WHERE enabled=TRUE ORDER BY id")
        else:
            rows = await conn.fetch("SELECT * FROM ads ORDER BY id")
    return [dict(r) for r in rows]


async def get_ad(ad_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM ads WHERE id=$1", ad_id)
    return dict(row) if row else None


async def add_ad(text: str, link: str | None, button_text: str = "Подробнее",
                 utm_source: str = "music_bot", utm_medium: str = "ad") -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO ads (text, link, button_text, utm_source, utm_medium)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
        """, text, link, button_text, utm_source, utm_medium)
    return row["id"]


async def update_ad(ad_id: int, **kwargs) -> bool:
    allowed = {"text", "link", "button_text", "enabled", "weight", "link_mode"}
    fields, values = [], []
    for i, (k, v) in enumerate(kwargs.items(), 1):
        if k not in allowed:
            continue
        fields.append(f"{k} = ${i}")
        values.append(v)
    if not fields:
        return False
    values.append(ad_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE ads SET {', '.join(fields)} WHERE id = ${len(values)}",
            *values,
        )
    return True


async def delete_ad(ad_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM ads WHERE id=$1", ad_id)
    return res.endswith("1")


async def toggle_ad(ad_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "UPDATE ads SET enabled=NOT enabled WHERE id=$1 RETURNING enabled", ad_id
        )
    return bool(row and row["enabled"])


async def log_ad_action(ad_id: int, user_id: int, action: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO ad_stats (ad_id, user_id, action) VALUES ($1, $2, $3)",
            ad_id, user_id, action,
        )


async def get_ad_stats(ad_id: int, days: int = 7) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        shows = await conn.fetchval(f"""
            SELECT COUNT(*) FROM ad_stats
            WHERE ad_id=$1 AND action='show'
            AND created_at >= NOW() - INTERVAL '{int(days)} days'
        """, ad_id) or 0
        clicks = await conn.fetchval(f"""
            SELECT COUNT(*) FROM ad_stats
            WHERE ad_id=$1 AND action='click'
            AND created_at >= NOW() - INTERVAL '{int(days)} days'
        """, ad_id) or 0
    ctr = round((clicks / shows * 100), 1) if shows else 0.0
    return {"shows": shows, "clicks": clicks, "ctr": ctr}


async def get_all_ad_stats(days: int = 7) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        shows = await conn.fetchval(f"""
            SELECT COUNT(*) FROM ad_stats WHERE action='show'
            AND created_at >= NOW() - INTERVAL '{int(days)} days'
        """) or 0
        clicks = await conn.fetchval(f"""
            SELECT COUNT(*) FROM ad_stats WHERE action='click'
            AND created_at >= NOW() - INTERVAL '{int(days)} days'
        """) or 0
    ctr = round((clicks / shows * 100), 1) if shows else 0.0
    return {"shows": shows, "clicks": clicks, "ctr": ctr}


async def pick_random_ad():
    ads = await get_all_ads(only_enabled=True)
    if not ads:
        return None
    import random
    weights = [max(1, a.get("weight", 1)) for a in ads]
    return random.choices(ads, weights=weights, k=1)[0]


# ============================================================
# EXTRA ADMINS
# ============================================================

async def is_main_admin(user_id: int) -> bool:
    return user_id in config.ADMIN_IDS


async def get_extra_admins() -> list[int]:
    data = await get_setting("extra_admins", [])
    if not isinstance(data, list):
        return []
    return [int(x) for x in data if str(x).isdigit()]


async def add_extra_admin(user_id: int, added_by: int) -> bool:
    current = await get_extra_admins()
    if user_id in current or user_id in config.ADMIN_IDS:
        return False
    current.append(user_id)
    await set_setting("extra_admins", current)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO admins (user_id, added_by) VALUES ($1, $2)
            ON CONFLICT DO NOTHING
        """, user_id, added_by)
    return True


async def remove_extra_admin(user_id: int) -> bool:
    current = await get_extra_admins()
    if user_id not in current:
        return False
    current.remove(user_id)
    await set_setting("extra_admins", current)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM admins WHERE user_id=$1", user_id)
    return True


# ============================================================
# STATS
# ============================================================

async def get_stats() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
        paid = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_paid=TRUE") or 0
        banned = await conn.fetchval("SELECT COUNT(*) FROM users WHERE is_banned=TRUE") or 0
        active7 = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE last_seen > NOW() - INTERVAL '7 days'"
        ) or 0
        cached = await conn.fetchval("SELECT COUNT(*) FROM track_cache") or 0
        hits = await conn.fetchval("SELECT COALESCE(SUM(hits),0) FROM track_cache") or 0
        stars = await conn.fetchval("SELECT COALESCE(SUM(stars_paid),0) FROM payments") or 0
        payments_count = await conn.fetchval("SELECT COUNT(*) FROM payments") or 0
        downloads_today = await conn.fetchval(
            "SELECT COALESCE(SUM(count),0) FROM download_usage WHERE usage_date=CURRENT_DATE"
        ) or 0
    return {
        "total": total,
        "paid": paid,
        "free": total - paid,
        "banned": banned,
        "active7": active7,
        "cached": cached,
        "cache_hits": hits,
        "total_stars": stars,
        "total_payments": payments_count,
        "downloads_today": downloads_today,
    }


async def list_one_time_features(only_enabled: bool = False) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if only_enabled:
            rows = await conn.fetch("SELECT * FROM one_time_features WHERE enabled=TRUE ORDER BY id")
        else:
            rows = await conn.fetch("SELECT * FROM one_time_features ORDER BY id")
    return [dict(r) for r in rows]


async def get_one_time_feature(feature_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM one_time_features WHERE id=$1", feature_id)
    return dict(row) if row else None


async def add_one_time_feature(code: str, name: str, description: str = "", price_stars: int = 0, uses_limit: int = 1) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO one_time_features (code, name, description, price_stars, uses_limit)
            VALUES ($1, $2, $3, $4, $5) RETURNING id
        """, code, name, description, price_stars, uses_limit)
    return row["id"]


async def update_one_time_feature(feature_id: int, **kwargs) -> bool:
    allowed = {"name", "description", "price_stars", "uses_limit", "enabled"}
    fields, values = [], []
    for i, (k, v) in enumerate(kwargs.items(), 1):
        if k in allowed:
            fields.append(f"{k} = ${i}")
            values.append(v)
    if not fields:
        return False
    values.append(feature_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE one_time_features SET {', '.join(fields)} WHERE id = ${len(values)}",
            *values,
        )
    return True


async def delete_one_time_feature(feature_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM one_time_features WHERE id=$1", feature_id)
    return res.endswith("1")


async def grant_user_feature(user_id: int, feature_id: int, uses_left: int, given_by: int | None = None, expires_at=None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO user_features (user_id, feature_id, uses_left, expires_at, given_by)
            VALUES ($1, $2, $3, $4, $5)
        """, user_id, feature_id, uses_left, expires_at, given_by)


async def revoke_user_feature(record_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        res = await conn.execute("DELETE FROM user_features WHERE id=$1", record_id)
    return res.endswith("1")


async def get_user_features(user_id: int) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT uf.*, f.code, f.name, f.description, f.price_stars
            FROM user_features uf
            JOIN one_time_features f ON f.id = uf.feature_id
            WHERE uf.user_id=$1
            ORDER BY uf.given_at DESC
        """, user_id)
    return [dict(r) for r in rows]


async def set_subscription_manual(user_id: int, end_date, is_paid: bool):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE users SET is_paid=$2, subscription_end=$3 WHERE user_id=$1
        """, user_id, is_paid, end_date)


async def revoke_subscription(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE users SET is_paid=FALSE, subscription_end=NULL WHERE user_id=$1
        """, user_id)


async def reset_trial_for_user(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE users SET trial_used=FALSE, trial_used_at=NULL WHERE user_id=$1
        """, user_id)


async def list_users(page: int, per_page: int = 10, search: str | None = None) -> tuple:
    pool = await get_pool()
    offset = page * per_page
    async with pool.acquire() as conn:
        if search:
            pattern = f"%{search}%"
            total = await conn.fetchval("""
                SELECT COUNT(*) FROM users
                WHERE CAST(user_id AS TEXT) LIKE $1 OR username ILIKE $1 OR first_name ILIKE $1
            """, pattern) or 0
            rows = await conn.fetch("""
                SELECT user_id, username, first_name, is_banned, is_paid,
                       subscription_end, trial_used, created_at, last_seen
                FROM users
                WHERE CAST(user_id AS TEXT) LIKE $1 OR username ILIKE $1 OR first_name ILIKE $1
                ORDER BY created_at DESC LIMIT $2 OFFSET $3
            """, pattern, per_page, offset)
        else:
            total = await conn.fetchval("SELECT COUNT(*) FROM users") or 0
            rows = await conn.fetch("""
                SELECT user_id, username, first_name, is_banned, is_paid,
                       subscription_end, trial_used, created_at, last_seen
                FROM users ORDER BY created_at DESC LIMIT $1 OFFSET $2
            """, per_page, offset)
    return ([dict(r) for r in rows], total)


async def clean_track_cache(mode: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if mode == "all":
            res = await conn.execute("DELETE FROM track_cache")
        elif mode == "old":
            res = await conn.execute(
                "DELETE FROM track_cache WHERE created_at < NOW() - INTERVAL '90 days'"
            )
        else:
            res = await conn.execute(
                "DELETE FROM track_cache WHERE hits = 0 AND created_at < NOW() - INTERVAL '7 days'"
            )
    try:
        return int(res.split()[-1])
    except Exception:
        return 0

async def get_action_prices() -> dict:
    data = await get_setting("action_prices", config.DEFAULT_ACTION_PRICES)
    if not isinstance(data, dict):
        return config.DEFAULT_ACTION_PRICES
    result = dict(config.DEFAULT_ACTION_PRICES)
    result.update(data)
    return result


async def set_action_price(action_key: str, price: int):
    prices = await get_action_prices()
    prices[action_key] = price
    await set_setting("action_prices", prices)


async def get_billing_mode() -> dict:
    data = await get_setting("billing_mode", config.DEFAULT_BILLING_MODE)
    if not isinstance(data, dict):
        return config.DEFAULT_BILLING_MODE
    result = dict(config.DEFAULT_BILLING_MODE)
    result.update(data)
    return result


async def set_billing_mode(**kwargs):
    mode = await get_billing_mode()
    for k, v in kwargs.items():
        mode[k] = v
    await set_setting("billing_mode", mode)


async def get_balance(user_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT balance FROM user_balances WHERE user_id=$1", user_id)
    return int(row["balance"]) if row else 0


async def add_balance(user_id: int, amount: int, kind: str = "manual",
                      action: str = None, note: str = None,
                      created_by: int = None) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                INSERT INTO user_balances (user_id, balance) VALUES ($1, 0)
                ON CONFLICT (user_id) DO NOTHING
            """, user_id)
            await conn.execute("""
                UPDATE user_balances
                SET balance = balance + $1, updated_at = NOW()
                WHERE user_id = $2
            """, amount, user_id)
            new_balance = await conn.fetchval(
                "SELECT balance FROM user_balances WHERE user_id=$1", user_id
            )
            await conn.execute("""
                INSERT INTO transactions (user_id, amount, kind, action, note, created_by)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, user_id, amount, kind, action, note, created_by)
    return int(new_balance or 0)


async def get_transactions(user_id: int, limit: int = 10) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT amount, kind, action, note, created_at
            FROM transactions WHERE user_id=$1
            ORDER BY created_at DESC LIMIT $2
        """, user_id, limit)
    return [dict(r) for r in rows]


async def get_total_free_actions_used(user_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval("""
            SELECT COALESCE(SUM(count),0) FROM usage_counters
            WHERE user_id=$1 AND usage_date=CURRENT_DATE
        """, user_id)
    return int(val or 0)


async def increment_free_action(user_id: int, action_key: str) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO usage_counters (user_id, usage_date, action, count)
            VALUES ($1, CURRENT_DATE, $2, 1)
            ON CONFLICT (user_id, usage_date, action) DO UPDATE
            SET count = usage_counters.count + 1
        """, user_id, action_key)
        val = await conn.fetchval("""
            SELECT count FROM usage_counters
            WHERE user_id=$1 AND usage_date=CURRENT_DATE AND action=$2
        """, user_id, action_key)
    return int(val or 0)


async def check_action_access(user_id: int, action_key: str):
    if config.FREE_MODE:
        return (True, "free_mode", 0, await get_balance(user_id))

    mode = await get_billing_mode()
    if mode.get("subscription_enabled") and await is_paid(user_id):
        return (True, "subscription", 0, await get_balance(user_id))

    free_limit = int(mode.get("free_actions_per_day", 0))
    if free_limit > 0:
        used = await get_total_free_actions_used(user_id)
        if used < free_limit:
            return (True, "free_quota", 0, await get_balance(user_id))

    if mode.get("pay_per_use_enabled"):
        prices = await get_action_prices()
        price = int(prices.get(action_key, 0))
        balance = await get_balance(user_id)
        if price <= 0:
            return (True, "pay_per_use", 0, balance)
        if balance >= price:
            return (True, "pay_per_use", price, balance)
        return (False, "need_topup", price, balance)

    return (False, "no_access", 0, await get_balance(user_id))


async def finalize_action(user_id: int, action_key: str, reason: str, price: int) -> int:
    if reason == "free_quota":
        await increment_free_action(user_id, action_key)
        return await get_balance(user_id)
    if reason == "pay_per_use" and price > 0:
        return await add_balance(user_id, -price, kind="charge", action=action_key)
    return await get_balance(user_id)

# ============================================================
# WITHDRAWALS (вывод средств админом)
# ============================================================

async def add_withdrawal(amount: int, note: str = "", created_by: int = None) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO withdrawals (amount, note, created_by)
            VALUES ($1, $2, $3) RETURNING id
        """, amount, note, created_by)
    return row["id"]


async def get_withdrawals(limit: int = 10) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT amount, note, created_at FROM withdrawals
            ORDER BY created_at DESC LIMIT $1
        """, limit)
    return [dict(r) for r in rows]


async def get_withdrawal_stats() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        subs_income = await conn.fetchval(
            "SELECT COALESCE(SUM(stars_paid),0) FROM payments"
        ) or 0
        topup_income = await conn.fetchval(
            "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE kind='topup'"
        ) or 0
        on_balances = await conn.fetchval(
            "SELECT COALESCE(SUM(balance),0) FROM user_balances"
        ) or 0
        withdrawn = await conn.fetchval(
            "SELECT COALESCE(SUM(amount),0) FROM withdrawals"
        ) or 0
    total_income = subs_income + topup_income
    available = max(0, total_income - withdrawn - on_balances)
    return {
        "total_income": total_income,
        "subs_income": subs_income,
        "topup_income": topup_income,
        "on_balances": on_balances,
        "withdrawn": withdrawn,
        "available": available,
    }

async def get_analytics(days: int = 7) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        d = int(days)
        new_users = await conn.fetchval(
            f"SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '{d} days'"
        ) or 0
        downloads = await conn.fetchval(
            f"SELECT COALESCE(SUM(count),0) FROM usage_counters WHERE usage_date >= CURRENT_DATE - INTERVAL '{d} days'"
        ) or 0
        subs_income = await conn.fetchval(
            f"SELECT COALESCE(SUM(stars_paid),0) FROM payments WHERE created_at >= NOW() - INTERVAL '{d} days'"
        ) or 0
        topup_income = await conn.fetchval(
            f"SELECT COALESCE(SUM(amount),0) FROM transactions WHERE kind='topup' AND created_at >= NOW() - INTERVAL '{d} days'"
        ) or 0
        new_paid = await conn.fetchval(
            f"SELECT COUNT(DISTINCT user_id) FROM payments WHERE created_at >= NOW() - INTERVAL '{d} days'"
        ) or 0
        active = await conn.fetchval(
            f"SELECT COUNT(*) FROM users WHERE last_seen >= NOW() - INTERVAL '{d} days'"
        ) or 0
    return {
        "days": days,
        "new_users": new_users,
        "new_paid": new_paid,
        "active": active,
        "downloads": downloads,
        "subs_income": subs_income,
        "topup_income": topup_income,
        "total_income": subs_income + topup_income,
    }


async def get_users_for_filter(filter_type: str) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if filter_type == "paid":
            rows = await conn.fetch("SELECT user_id FROM users WHERE is_paid=TRUE AND is_banned=FALSE")
        elif filter_type == "free":
            rows = await conn.fetch("SELECT user_id FROM users WHERE is_paid=FALSE AND is_banned=FALSE")
        elif filter_type == "active7":
            rows = await conn.fetch("SELECT user_id FROM users WHERE last_seen >= NOW() - INTERVAL '7 days' AND is_banned=FALSE")
        elif filter_type == "with_balance":
            rows = await conn.fetch("""
                SELECT ub.user_id FROM user_balances ub
                JOIN users u ON u.user_id = ub.user_id
                WHERE ub.balance > 0 AND u.is_banned = FALSE
            """)
        else:
            rows = await conn.fetch("SELECT user_id FROM users WHERE is_banned=FALSE")
    return [r["user_id"] for r in rows]


async def get_users_export() -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.user_id, u.username, u.first_name, u.is_paid,
                   u.subscription_end, u.trial_used, u.is_banned,
                   u.created_at, u.last_seen,
                   COALESCE(ub.balance, 0) AS balance
            FROM users u
            LEFT JOIN user_balances ub ON ub.user_id = u.user_id
            ORDER BY u.created_at DESC
        """)
    return [dict(r) for r in rows]

# ============================================================
# DOWNLOADS HISTORY
# ============================================================

async def add_download_history(user_id: int, url: str, title: str,
                                performer: str, platform: str, file_id: str = None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO downloads_history (user_id, url, title, performer, platform, file_id)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, user_id, url, title, performer, platform, file_id)


async def get_user_downloads(user_id: int, limit: int = 10) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT title, performer, platform, url, downloaded_at
            FROM downloads_history
            WHERE user_id = $1
            ORDER BY downloaded_at DESC LIMIT $2
        """, user_id, limit)
    return [dict(r) for r in rows]


async def count_user_downloads(user_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT COUNT(*) FROM downloads_history WHERE user_id=$1", user_id
        )
    return int(val or 0)