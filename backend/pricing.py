"""
定價規則
------------
價格數字已改為存放在資料庫的 pricing_config 表,後台主管可直接調整,
不需要再請工程師改程式碼。這裡的 compute_* 函式邏輯維持原本設計,
只是改成從資料庫讀值,而不是寫死的常數。
"""

import json
from datetime import datetime, timedelta, timezone

from db import get_conn, NOW_SQL

TW_TZ = timezone(timedelta(hours=8))


def _now_tw():
    return datetime.now(TW_TZ).replace(tzinfo=None)


# ---------------- 固定不隨價格調整的營運規則(季節/雪季區間定義本身不算「價格」,維持常數) ----------------
JAPAN_SEASON_MONTHS = {12, 1, 2, 3, 4}  # 每年12月-隔年4月
SUMMER_MONTHS = {4, 5, 6, 7, 8, 9}
WINTER_MONTHS = {10, 11, 12, 1, 2, 3}
GROUP_CLASS_ALLOW_COACH_CHOICE = False  # 團課不可指定教練


def get_config(key, default=None):
    """從 pricing_config 讀取一筆設定值(JSON解析後回傳)。找不到則回傳 default。"""
    conn = get_conn()
    row = conn.execute("SELECT config_value FROM pricing_config WHERE config_key=?", (key,)).fetchone()
    conn.close()
    if not row:
        return default
    return json.loads(row["config_value"])


def set_config(key, value, staff_id=None):
    """後台寫入一筆價格設定(value 會被轉成 JSON 字串儲存)。"""
    conn = get_conn()
    conn.execute(
        f"""UPDATE pricing_config SET config_value=?, updated_at={NOW_SQL}, updated_by_staff_id=?
           WHERE config_key=?""",
        (json.dumps(value), staff_id, key),
    )
    conn.commit()
    conn.close()


def list_all_configs():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM pricing_config ORDER BY config_key").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# 為了向下相容:模組屬性存取(例如 pricing.INDOOR_START_HOUR)一律動態轉呼叫 get_config,
# 避免每個呼叫端都要改成 pricing.get_config("indoor_start_hour")。
_ATTR_KEY_MAP = {
    "INDOOR_START_HOUR": "indoor_start_hour",
    "INDOOR_LAST_START_HOUR": "indoor_last_start_hour",
    "GROUP_CLASS_MIN": "group_class_min",
    "GROUP_CLASS_MAX": "group_class_max",
    "GROUP_CLASS_PRICE": "group_class_price",
    "BOOKING_WINDOW_DAYS": "booking_window_days",
}


def __getattr__(name):
    """PEP 562:模組層級的動態屬性存取,讓 pricing.INDOOR_START_HOUR 這類舊寫法繼續可用。"""
    if name in _ATTR_KEY_MAP:
        return get_config(_ATTR_KEY_MAP[name])
    raise AttributeError(f"module 'pricing' has no attribute {name!r}")


def season_period_and_year(date_str):
    """回傳 (season_period, season_year)。冬季(10-3月)以10月所在年份當作 season_year。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if dt.month in SUMMER_MONTHS:
        return "summer", str(dt.year)
    else:
        year = dt.year if dt.month >= 10 else dt.year - 1
        return "winter", str(year)


def compute_trial_price(headcount):
    table = get_config("trial_price", {})
    key = str(headcount)
    if key not in table:
        raise ValueError("體驗課人數僅接受 1~4 人")
    return table[key]


def compute_charter_price(package_size, headcount):
    table = get_config("charter_price", {})
    pkg_key, hc_key = str(package_size), str(headcount)
    if pkg_key not in table:
        raise ValueError("包機堂數僅接受 5 或 10 堂")
    if hc_key not in table[pkg_key]:
        raise ValueError("包機課人數僅接受 1對1 或 1對2")
    return table[pkg_key][hc_key]


def compute_self_practice_price(duration_minutes):
    table = get_config("self_practice_price", {})
    key = str(duration_minutes)
    if key not in table:
        raise ValueError("自主練習時長僅接受 30 / 60 / 120 分鐘")
    return table[key]


def compute_jump_price(duration_minutes):
    table = get_config("jump_price", {})
    key = str(duration_minutes)
    if key not in table:
        raise ValueError("跳台體驗時長僅接受 60 / 120 分鐘")
    return table[key]


def compute_japan_price(day_type, headcount, designate_coach):
    table = get_config("japan_full_day_price" if day_type == "full" else "japan_half_day_price", {})
    key = str(headcount)
    if key not in table:
        raise ValueError("日本教練課人數僅接受 1~4 人")
    price = table[key]
    if designate_coach:
        price += get_config("japan_coach_designate_fee", 0)
    return price


def get_plan_quota(plan_name, season_period):
    table = get_config("plan_quota", {})
    if plan_name not in table:
        raise ValueError("方案僅接受 A 或 B")
    return table[plan_name][season_period]


def get_plan_fee(plan_name, billing_cycle):
    table = get_config("plan_fee", {})
    return table[plan_name][billing_cycle]


def validate_booking_window(date_str):
    """首次體驗/自主練習/團課 僅能預約「今天~未來N天內」(N由後台設定)。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d").date()
    today = _now_tw().date()
    window_days = get_config("booking_window_days", 30)
    if dt < today:
        raise ValueError("不能預約過去的日期")
    if dt > today + timedelta(days=window_days):
        raise ValueError(f"僅開放未來 {window_days} 天內的日期預約")


def validate_japan_season(date_str):
    """日本教練課固定每年12月至隔年4月為雪季開放預約。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if dt.month not in JAPAN_SEASON_MONTHS:
        raise ValueError(f"{date_str} 不在雪季範圍內(每年12月至隔年4月才開放預約)")
