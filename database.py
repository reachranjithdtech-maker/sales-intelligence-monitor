import sqlite3
import os
import csv
import json
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "salesintel.db")


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS prospects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_name TEXT NOT NULL UNIQUE,
            website TEXT,
            country TEXT,
            city TEXT,
            street TEXT,
            stock_symbol TEXT,
            zip_code TEXT,
            industry TEXT,
            linkedin_id TEXT,
            linkedin_url TEXT,
            region TEXT,
            segment TEXT,
            priority TEXT DEFAULT 'medium',
            status TEXT DEFAULT 'monitoring',
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prospect_id INTEGER NOT NULL,
            signal_type TEXT NOT NULL,
            headline TEXT NOT NULL,
            summary TEXT,
            source TEXT,
            source_url TEXT,
            severity TEXT DEFAULT 'medium',
            detected_at TEXT DEFAULT (datetime('now')),
            is_read INTEGER DEFAULT 0,
            is_dismissed INTEGER DEFAULT 0,
            FOREIGN KEY (prospect_id) REFERENCES prospects(id)
        );

        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER,
            prospect_id INTEGER NOT NULL,
            context TEXT,
            business_implication TEXT,
            comcast_opportunity TEXT,
            recommended_action TEXT,
            urgency TEXT DEFAULT 'medium',
            confidence_score REAL DEFAULT 0.0,
            opportunity_value TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (signal_id) REFERENCES signals(id),
            FOREIGN KEY (prospect_id) REFERENCES prospects(id)
        );

        CREATE TABLE IF NOT EXISTS action_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_id INTEGER NOT NULL,
            prospect_id INTEGER NOT NULL,
            action_text TEXT NOT NULL,
            action_type TEXT,
            assigned_to TEXT,
            due_date TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT,
            FOREIGN KEY (analysis_id) REFERENCES analyses(id),
            FOREIGN KEY (prospect_id) REFERENCES prospects(id)
        );

        CREATE INDEX IF NOT EXISTS idx_signals_prospect ON signals(prospect_id);
        CREATE INDEX IF NOT EXISTS idx_signals_type ON signals(signal_type);
        CREATE INDEX IF NOT EXISTS idx_signals_detected ON signals(detected_at);
        CREATE INDEX IF NOT EXISTS idx_analyses_prospect ON analyses(prospect_id);
        CREATE INDEX IF NOT EXISTS idx_action_items_status ON action_items(status);
    """)
    conn.commit()
    conn.close()


REGION_MAP = {
    "india": ["Sony", "Disney", "Zee", "Viacom18", "Sun TV", "ETV", "Network18",
              "Tata Play", "Airtel", "Jio"],
    "southeast_asia": ["Mediacorp", "TRUE", "GMM", "VTV", "ABS-CBN", "Media Prima",
                       "MNC", "Trans Media", "Singtel", "StarHub", "Telkomsel",
                       "Indosat", "AIS", "PLDT", "Maxis"],
    "japan": ["NHK", "Nippon TV", "Fuji TV", "TV Asahi", "TBS", "NTT", "KDDI",
              "SoftBank", "J:COM", "Hulu Japan", "U-Next"],
    "korea": ["KBS", "MBC", "SBS", "SK Telecom", "KT", "LG U+"],
    "anz": ["ABC", "Seven", "Nine", "Network 10", "Foxtel", "Telstra", "Optus", "Sky NZ"],
}

SEGMENT_MAP = {
    "broadcaster": ["Sony", "Disney", "Zee", "Sun TV", "ETV", "Network18", "Mediacorp",
                    "GMM", "VTV", "ABS-CBN", "Media Prima", "MNC", "Trans Media",
                    "NHK", "Nippon TV", "Fuji TV", "TV Asahi", "TBS", "KBS", "MBC",
                    "SBS", "ABC", "Seven", "Nine", "Network 10"],
    "ott_platform": ["Viacom18", "JioCinema", "Sony LIV", "ZEE5", "JioStar",
                     "Hulu Japan", "U-Next", "Foxtel", "TRUE", "TRUEID", "Sky NZ"],
    "telecom": ["Jio", "Airtel", "Tata Play", "Singtel", "StarHub", "Telkomsel",
                "Indosat", "AIS", "True Corp", "PLDT", "Smart", "Maxis", "NTT",
                "KDDI", "SoftBank", "SK Telecom", "KT", "LG U+", "Telstra", "Optus"],
    "cable_dth": ["J:COM", "Tata Play", "Cignal", "Foxtel", "Astro", "Sky NZ"],
}


def classify_prospect(name):
    region = "other"
    for r, keywords in REGION_MAP.items():
        if any(k.lower() in name.lower() for k in keywords):
            region = r
            break

    segment = "other"
    for s, keywords in SEGMENT_MAP.items():
        if any(k.lower() in name.lower() for k in keywords):
            segment = s
            break

    return region, segment


def import_csv(filepath):
    conn = get_db()
    imported = 0
    skipped = 0

    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("Account Name (REQUIRED)", "").strip()
            if not name:
                continue

            region, segment = classify_prospect(name)

            try:
                conn.execute("""
                    INSERT INTO prospects (account_name, website, country, city, street,
                        stock_symbol, zip_code, industry, linkedin_id, linkedin_url,
                        region, segment)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    name,
                    row.get("Website URL (OPTIONAL)", "").strip() or None,
                    row.get("Country (OPTIONAL)", "").strip() or None,
                    row.get("City (OPTIONAL)", "").strip() or None,
                    row.get("Street (OPTIONAL)", "").strip() or None,
                    row.get("Stock symbol (OPTIONAL)", "").strip() or None,
                    row.get("Zip/Postal Code (OPTIONAL)", "").strip() or None,
                    row.get("Industry (OPTIONAL)", "").strip() or None,
                    row.get("LinkedIn Company ID (OPTIONAL)", "").strip() or None,
                    row.get("LinkedIn Company URL (OPTIONAL)", "").strip() or None,
                    region,
                    segment,
                ))
                imported += 1
            except sqlite3.IntegrityError:
                skipped += 1

    conn.commit()
    conn.close()
    return imported, skipped


def get_all_prospects(region=None, segment=None, search=None):
    conn = get_db()
    query = "SELECT * FROM prospects WHERE 1=1"
    params = []

    if region and region != "all":
        query += " AND region = ?"
        params.append(region)
    if segment and segment != "all":
        query += " AND segment = ?"
        params.append(segment)
    if search:
        query += " AND account_name LIKE ?"
        params.append(f"%{search}%")

    query += " ORDER BY account_name"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_prospect(prospect_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM prospects WHERE id = ?", (prospect_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_signals(prospect_id=None, signal_type=None, limit=50):
    conn = get_db()
    query = """
        SELECT s.*, p.account_name
        FROM signals s
        JOIN prospects p ON s.prospect_id = p.id
        WHERE s.is_dismissed = 0
    """
    params = []

    if prospect_id:
        query += " AND s.prospect_id = ?"
        params.append(prospect_id)
    if signal_type and signal_type != "all":
        query += " AND s.signal_type = ?"
        params.append(signal_type)

    query += " ORDER BY s.detected_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_signal(prospect_id, signal_type, headline, summary=None,
               source=None, source_url=None, severity="medium"):
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO signals (prospect_id, signal_type, headline, summary, source,
            source_url, severity)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (prospect_id, signal_type, headline, summary, source, source_url, severity))
    signal_id = cur.lastrowid
    conn.commit()
    conn.close()
    return signal_id


def save_analysis(signal_id, prospect_id, context, business_implication,
                  comcast_opportunity, recommended_action, urgency="medium",
                  confidence_score=0.0, opportunity_value=None):
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO analyses (signal_id, prospect_id, context, business_implication,
            comcast_opportunity, recommended_action, urgency, confidence_score,
            opportunity_value)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (signal_id, prospect_id, context, business_implication,
          comcast_opportunity, recommended_action, urgency, confidence_score,
          opportunity_value))
    analysis_id = cur.lastrowid
    conn.commit()
    conn.close()
    return analysis_id


def get_analyses(prospect_id=None, limit=50):
    conn = get_db()
    query = """
        SELECT a.*, s.headline as signal_headline, s.signal_type, s.severity,
               p.account_name
        FROM analyses a
        LEFT JOIN signals s ON a.signal_id = s.id
        JOIN prospects p ON a.prospect_id = p.id
        WHERE 1=1
    """
    params = []

    if prospect_id:
        query += " AND a.prospect_id = ?"
        params.append(prospect_id)

    query += " ORDER BY a.created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_dashboard_stats():
    conn = get_db()
    stats = {}
    stats["total_prospects"] = conn.execute(
        "SELECT COUNT(*) FROM prospects").fetchone()[0]
    stats["total_signals"] = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE is_dismissed = 0").fetchone()[0]
    stats["unread_signals"] = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE is_read = 0 AND is_dismissed = 0"
    ).fetchone()[0]
    stats["total_analyses"] = conn.execute(
        "SELECT COUNT(*) FROM analyses").fetchone()[0]
    stats["pending_actions"] = conn.execute(
        "SELECT COUNT(*) FROM action_items WHERE status = 'pending'"
    ).fetchone()[0]
    stats["high_urgency"] = conn.execute(
        "SELECT COUNT(*) FROM analyses WHERE urgency = 'high'"
    ).fetchone()[0]

    stats["by_region"] = [dict(r) for r in conn.execute(
        "SELECT region, COUNT(*) as count FROM prospects GROUP BY region ORDER BY count DESC"
    ).fetchall()]

    stats["by_segment"] = [dict(r) for r in conn.execute(
        "SELECT segment, COUNT(*) as count FROM prospects GROUP BY segment ORDER BY count DESC"
    ).fetchall()]

    stats["by_signal_type"] = [dict(r) for r in conn.execute("""
        SELECT signal_type, COUNT(*) as count FROM signals
        WHERE is_dismissed = 0
        GROUP BY signal_type ORDER BY count DESC
    """).fetchall()]

    stats["recent_signals"] = [dict(r) for r in conn.execute("""
        SELECT s.*, p.account_name FROM signals s
        JOIN prospects p ON s.prospect_id = p.id
        WHERE s.is_dismissed = 0
        ORDER BY s.detected_at DESC LIMIT 10
    """).fetchall()]

    stats["recent_analyses"] = [dict(r) for r in conn.execute("""
        SELECT a.*, s.headline as signal_headline, s.signal_type, p.account_name
        FROM analyses a
        LEFT JOIN signals s ON a.signal_id = s.id
        JOIN prospects p ON a.prospect_id = p.id
        ORDER BY a.created_at DESC LIMIT 5
    """).fetchall()]

    conn.close()
    return stats


def mark_signal_read(signal_id):
    conn = get_db()
    conn.execute("UPDATE signals SET is_read = 1 WHERE id = ?", (signal_id,))
    conn.commit()
    conn.close()


def dismiss_signal(signal_id):
    conn = get_db()
    conn.execute("UPDATE signals SET is_dismissed = 1 WHERE id = ?", (signal_id,))
    conn.commit()
    conn.close()


def add_action_item(analysis_id, prospect_id, action_text, action_type=None,
                    assigned_to=None, due_date=None):
    conn = get_db()
    conn.execute("""
        INSERT INTO action_items (analysis_id, prospect_id, action_text,
            action_type, assigned_to, due_date)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (analysis_id, prospect_id, action_text, action_type, assigned_to, due_date))
    conn.commit()
    conn.close()


def get_action_items(status=None, prospect_id=None):
    conn = get_db()
    query = """
        SELECT ai.*, p.account_name, a.comcast_opportunity
        FROM action_items ai
        JOIN prospects p ON ai.prospect_id = p.id
        JOIN analyses a ON ai.analysis_id = a.id
        WHERE 1=1
    """
    params = []
    if status and status != "all":
        query += " AND ai.status = ?"
        params.append(status)
    if prospect_id:
        query += " AND ai.prospect_id = ?"
        params.append(prospect_id)
    query += " ORDER BY ai.created_at DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_action_status(action_id, status):
    conn = get_db()
    extra = ""
    if status == "completed":
        extra = ", completed_at = datetime('now')"
    conn.execute(
        f"UPDATE action_items SET status = ?{extra} WHERE id = ?",
        (status, action_id)
    )
    conn.commit()
    conn.close()
