"""
固定定價規則
------------
這些數字是業主提供的定價表,先寫成程式碼常數方便快速上線與測試;
之後如果想在後台介面直接改價格,可以把這個檔案改成從資料庫的
pricing_tiers 表讀取,邏輯(compute_* 函式)完全不用動。
"""

from datetime import datetime, timedelta

# ---------------- 預約時間窗 ----------------
BOOKING_WINDOW_DAYS = 30  # 首次體驗/自主練習/團課 僅開放未來1個月內預約

# ---------------- 日本教練課雪季 ----------------
JAPAN_SEASON_MONTHS = {12, 1, 2, 3, 4}  # 每年12月-隔年4月

# ---------------- 室內滑雪:體驗 ----------------
TRIAL_PRICE = {1: 1500, 2: 2500, 3: 3500, 4: 4500}

# ---------------- 室內滑雪:包機(堂數包) ----------------
CHARTER_PRICE = {
    5: {1: 8500, 2: 13000},
    10: {1: 16000, 2: 24000},
}

# ---------------- 室內滑雪:自主練習 ----------------
SELF_PRACTICE_PRICE = {30: 300, 60: 500, 120: 800}

# ---------------- 跳台體驗 ----------------
JUMP_PRICE = {60: 300, 120: 500}

# ---------------- 團課 ----------------
# 假設:團課本身不另外收費,僅限已被後台指派 A/B 方案的會員報名。
# 若之後要改成額外收費,把這裡改成類似 TRIAL_PRICE 的 dict 即可。
GROUP_CLASS_PRICE = None  # None = 不另外收費(算在會員資格內)

# ---------------- 日本教練課 ----------------
JAPAN_FULL_DAY_PRICE = {1: 15000, 2: 16500, 3: 18000, 4: 19500}
JAPAN_HALF_DAY_PRICE = {1: 11000, 2: 12000, 3: 13000, 4: 14000}
JAPAN_COACH_DESIGNATE_FEE = 1000

# ---------------- 團課規則 ----------------
GROUP_CLASS_MIN = 2
GROUP_CLASS_MAX = 4
GROUP_CLASS_ALLOW_COACH_CHOICE = False  # 團課不可指定教練

# ---------------- 方案 A/B 會員資格年費/月費 ----------------
PLAN_FEE = {
    "A": {"annual": 2500, "monthly": 1500},
    "B": {"annual": 3500, "monthly": 2500},
}

# ---------------- 室內營業時間 ----------------
# 10:00~21:00,每堂課50分鐘整點開課,故最後一堂開課時間為 20:00(20:00-20:50)
INDOOR_START_HOUR = 10
INDOOR_LAST_START_HOUR = 20

# ---------------- A/B 會員方案:包機課+自主練習 每季額度 ----------------
# 假設:額度內預約 = 不用再額外付費(算會員福利);超額後才走一般定價。
PLAN_QUOTA = {
    "A": {
        "summer": {"charter": 2, "self_practice": 1, "group_class": 2},   # 4-9月
        "winter": {"charter": 1, "self_practice": 1, "group_class": 1},   # 10-次年3月
    },
    "B": {
        "summer": {"charter": 3, "self_practice": 2, "group_class": 3},
        "winter": {"charter": 2, "self_practice": 1, "group_class": 2},
    },
}
SUMMER_MONTHS = {4, 5, 6, 7, 8, 9}
WINTER_MONTHS = {10, 11, 12, 1, 2, 3}


def season_period_and_year(date_str):
    """回傳 (season_period, season_year)。冬季(10-3月)以10月所在年份當作 season_year。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if dt.month in SUMMER_MONTHS:
        return "summer", str(dt.year)
    else:
        year = dt.year if dt.month >= 10 else dt.year - 1
        return "winter", str(year)


def compute_trial_price(headcount):
    if headcount not in TRIAL_PRICE:
        raise ValueError("體驗課人數僅接受 1~4 人")
    return TRIAL_PRICE[headcount]


def compute_charter_price(package_size, headcount):
    if package_size not in CHARTER_PRICE:
        raise ValueError("包機堂數僅接受 5 或 10 堂")
    if headcount not in CHARTER_PRICE[package_size]:
        raise ValueError("包機課人數僅接受 1對1 或 1對2")
    return CHARTER_PRICE[package_size][headcount]


def compute_self_practice_price(duration_minutes):
    if duration_minutes not in SELF_PRACTICE_PRICE:
        raise ValueError("自主練習時長僅接受 30 / 60 / 120 分鐘")
    return SELF_PRACTICE_PRICE[duration_minutes]


def compute_jump_price(duration_minutes):
    if duration_minutes not in JUMP_PRICE:
        raise ValueError("跳台體驗時長僅接受 60 / 120 分鐘")
    return JUMP_PRICE[duration_minutes]


def compute_japan_price(day_type, headcount, designate_coach):
    table = JAPAN_FULL_DAY_PRICE if day_type == "full" else JAPAN_HALF_DAY_PRICE
    if headcount not in table:
        raise ValueError("日本教練課人數僅接受 1~4 人")
    price = table[headcount]
    if designate_coach:
        price += JAPAN_COACH_DESIGNATE_FEE
    return price


def get_plan_quota(plan_name, season_period):
    if plan_name not in PLAN_QUOTA:
        raise ValueError("方案僅接受 A 或 B")
    return PLAN_QUOTA[plan_name][season_period]


def validate_booking_window(date_str):
    """首次體驗/自主練習/團課 僅能預約「今天~未來1個月內」。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d").date()
    today = datetime.now().date()
    if dt < today:
        raise ValueError("不能預約過去的日期")
    if dt > today + timedelta(days=BOOKING_WINDOW_DAYS):
        raise ValueError(f"僅開放未來 {BOOKING_WINDOW_DAYS} 天內的日期預約")


def validate_japan_season(date_str):
    """日本教練課固定每年12月至隔年4月為雪季開放預約。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    if dt.month not in JAPAN_SEASON_MONTHS:
        raise ValueError(f"{date_str} 不在雪季範圍內(每年12月至隔年4月才開放預約)")
