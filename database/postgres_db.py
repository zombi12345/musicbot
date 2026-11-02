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
        ]:
            exists = await conn.fetchval("SELECT 1 FROM settings WHERE key=$1", key)
            if not exists:
                await conn.execute(
                    "INSERT INTO settings (key, value) VALUES ($1, $2)",
                    key, json.dumps(default, ensure_ascii=False),
                )
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