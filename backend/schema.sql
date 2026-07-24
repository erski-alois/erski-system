-- ============================================================
-- ERSki 滑雪急診室 預約系統 - 資料庫 Schema v2 (SQLite)
-- ============================================================

PRAGMA foreign_keys = ON;

-- ---------- 會員 ----------
CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    id_number TEXT,
    phone TEXT,
    emergency_contact_name TEXT,
    emergency_contact_phone TEXT,
    line_user_id TEXT UNIQUE,
    email TEXT UNIQUE,
    auth_provider TEXT CHECK(auth_provider IN ('line','google')) NOT NULL,
    internal_level TEXT,
    boot_size TEXT,
    board_length TEXT,
    -- 個人資料(會員自行於前台填寫維護)
    birth_date TEXT,
    gender TEXT CHECK(gender IN ('male','female')),
    blood_type TEXT,
    address TEXT,
    line_id TEXT,
    social_handle TEXT,               -- FB/IG/Threads
    height_cm REAL,
    weight_kg REAL,
    snowboard_length TEXT,
    snowboard_boot_size TEXT,
    ski_length TEXT,
    ski_boot_size TEXT,
    machine_level TEXT,               -- 雪機滑行程度
    snow_level TEXT,                  -- 雪上滑行程度
    primary_equipment TEXT CHECK(primary_equipment IN ('ski','snowboard')),  -- 會員主要滑行項目(用於會員編號)
    created_at TEXT DEFAULT (datetime('now'))
);

-- ---------- 員工(教練/客服/主管/老闆) ----------
CREATE TABLE IF NOT EXISTS staff (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    display_code TEXT,                  -- 前台顯示用代號,如「甲」「乙」「丙」
    phone TEXT,
    birthday TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT CHECK(role IN ('coach','cs','manager','boss')) NOT NULL,
    branch TEXT NOT NULL,
    is_coach BOOLEAN DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

-- ---------- 教練班表(上班/請假) ----------
CREATE TABLE IF NOT EXISTS coach_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coach_id INTEGER NOT NULL REFERENCES staff(id),
    work_date TEXT NOT NULL,
    status TEXT CHECK(status IN ('working','personal_leave','sick_leave','annual_leave','business_trip')) DEFAULT 'working',
    reason TEXT,
    UNIQUE(coach_id, work_date)
);

-- ============================================================
-- 室內滑雪(高雄機台 + 跳台)
-- ============================================================

-- 機台時段(體驗 / 包機 / 團課 / 自主練習 共用同一台機台,時段互斥)
CREATE TABLE IF NOT EXISTS indoor_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_date TEXT NOT NULL,
    start_hour INTEGER NOT NULL,
    duration_minutes INTEGER NOT NULL,
    category TEXT CHECK(category IN ('trial','charter','group_class','self_practice')) NOT NULL,
    coach_id INTEGER REFERENCES staff(id),
    max_capacity INTEGER NOT NULL DEFAULT 4,
    status TEXT CHECK(status IN (
        'pending_payment','open','confirmed','needs_manual_review','cancelled'
    )) DEFAULT 'pending_payment',
    charter_package_size INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS indoor_session_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES indoor_sessions(id),
    member_id INTEGER NOT NULL REFERENCES members(id),
    headcount INTEGER,
    equipment_type TEXT CHECK(equipment_type IN ('ski','snowboard')),
    price INTEGER,
    quota_consumed BOOLEAN DEFAULT 0,
    status TEXT CHECK(status IN ('enrolled','waitlisted','cancelled')) DEFAULT 'enrolled',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jump_bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id),
    booking_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    equipment_type TEXT CHECK(equipment_type IN ('ski','snowboard')),
    price INTEGER NOT NULL,
    status TEXT CHECK(status IN ('pending_payment','confirmed','cancelled')) DEFAULT 'pending_payment',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS charter_passes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id),
    package_size INTEGER NOT NULL,
    headcount_type INTEGER NOT NULL,
    remaining INTEGER NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS member_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id),
    plan_name TEXT CHECK(plan_name IN ('A','B')) NOT NULL,
    billing_cycle TEXT CHECK(billing_cycle IN ('annual','monthly')),
    fee_paid INTEGER,
    quota_cycle_start TEXT,   -- 額度週期起算日(第一次使用額度當天),滿一個月重新計算,不跟隨日曆季節
    assigned_by_staff_id INTEGER REFERENCES staff(id),
    is_active BOOLEAN DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

-- 以「額度週期」為單位的額度使用紀錄:
-- 月繳方案 cycle_key = 滾動月索引("0","1","2"...,以quota_cycle_start起算,每滿一個月換下一期)
-- 年繳方案 cycle_key = 季節+年份("2026-summer"/"2026-winter"),沿用原本4-9月/10-3月季節區間
CREATE TABLE IF NOT EXISTS member_quota_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id),
    cycle_key TEXT NOT NULL,
    charter_used INTEGER DEFAULT 0,
    self_practice_used INTEGER DEFAULT 0,
    group_class_used INTEGER DEFAULT 0,
    UNIQUE(member_id, cycle_key)
);

-- 月繳方案:每個月的繳費紀錄。當月未繳清前,該月無法使用方案額度(包機/自主練習/團課)
CREATE TABLE IF NOT EXISTS plan_billing_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_plan_id INTEGER NOT NULL REFERENCES member_plans(id),
    member_id INTEGER NOT NULL REFERENCES members(id),
    period TEXT NOT NULL,     -- YYYY-MM
    amount INTEGER NOT NULL,
    status TEXT CHECK(status IN ('pending','paid')) DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(member_plan_id, period)
);

-- ============================================================
-- 日本教練課
-- ============================================================

-- ---------- 日本滑雪分區(藏王/北海道/鬼首/白馬/其他) ----------
CREATE TABLE IF NOT EXISTS japan_regions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    requires_resort_selection BOOLEAN DEFAULT 1,   -- 是否需要客戶自選雪場
    allow_designate_coach BOOLEAN DEFAULT 1,       -- 是否開放客戶指定教練(其他雪場=否,只能校方指派)
    requires_accommodation_option BOOLEAN DEFAULT 0, -- 是否需詢問是否預訂住宿(鬼首=是)
    resort_list_editable BOOLEAN DEFAULT 0,        -- 雪場清單是否開放後台新增/刪減/修改
    display_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ski_resorts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    region_id INTEGER NOT NULL REFERENCES japan_regions(id),
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    is_active BOOLEAN DEFAULT 1
);

-- 雪場專屬教練名單(後台指派哪位教練負責哪個雪場,用於計算不指定教練時的容量)
CREATE TABLE IF NOT EXISTS resort_coaches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resort_id INTEGER NOT NULL REFERENCES ski_resorts(id),
    coach_id INTEGER NOT NULL REFERENCES staff(id),
    UNIQUE(resort_id, coach_id)
);

CREATE TABLE IF NOT EXISTS japan_bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id),
    resort_id INTEGER NOT NULL REFERENCES ski_resorts(id),
    booking_date TEXT NOT NULL,
    day_type TEXT CHECK(day_type IN ('half','full')) NOT NULL,
    half_day_slot TEXT CHECK(half_day_slot IN ('morning','afternoon')),
    headcount INTEGER NOT NULL,
    equipment_type TEXT CHECK(equipment_type IN ('ski','snowboard')),
    coach_id INTEGER REFERENCES staff(id),
    designate_coach BOOLEAN DEFAULT 0,
    needs_accommodation BOOLEAN DEFAULT 0,
    price INTEGER NOT NULL,
    group_key TEXT,
    status TEXT CHECK(status IN ('pending_payment','confirmed','cancelled')) DEFAULT 'pending_payment',
    created_at TEXT DEFAULT (datetime('now'))
);

-- 每筆預約(室內/跳台/日本)每一位參與者的基本資料
CREATE TABLE IF NOT EXISTS booking_participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_type TEXT CHECK(ref_type IN ('indoor_session_member','jump_booking','japan_booking')) NOT NULL,
    ref_id INTEGER NOT NULL,
    gender TEXT CHECK(gender IN ('male','female')),
    age INTEGER,
    height_cm REAL,
    weight_kg REAL,
    shoe_size TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- 團課方案申請(客戶申請,後台審核通過後才正式指派方案)
CREATE TABLE IF NOT EXISTS plan_applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id),
    plan_name TEXT CHECK(plan_name IN ('A','B')) NOT NULL,
    billing_cycle TEXT CHECK(billing_cycle IN ('annual','monthly')) NOT NULL,
    status TEXT CHECK(status IN ('pending','approved','rejected')) DEFAULT 'pending',
    reviewed_by_staff_id INTEGER REFERENCES staff(id),
    reviewed_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- 通知紀錄(LINE/Email/簡訊發送紀錄,目前為模擬記錄,未真正發送)
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER REFERENCES members(id),
    channel TEXT CHECK(channel IN ('line', 'email', 'sms', 'system')) DEFAULT 'system',
    notify_type TEXT NOT NULL,   -- booking_confirmed / group_class_cancelled / waitlist_promoted / payment_confirmed 等
    content TEXT NOT NULL,
    status TEXT CHECK(status IN ('sent', 'failed', 'simulated')) DEFAULT 'simulated',
    created_at TEXT DEFAULT (datetime('now'))
);

-- 教練團隊個人檔案(宣傳照/自我介紹/證件照)
CREATE TABLE IF NOT EXISTS coach_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coach_id INTEGER UNIQUE NOT NULL REFERENCES staff(id),
    promo_photo TEXT,      -- base64 圖片資料
    id_photo TEXT,         -- base64 圖片資料(證件照,內部使用)
    self_intro TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- 交易 / 付款 / CRM
-- ============================================================

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id),
    ref_type TEXT,
    ref_id INTEGER,
    amount INTEGER NOT NULL,
    payment_type TEXT CHECK(payment_type IN ('full','deposit_50')) DEFAULT 'full',
    payment_method TEXT CHECK(payment_method IN ('online_card','onsite','bank_transfer','manual_grant')),
    payment_status TEXT CHECK(payment_status IN ('pending','awaiting_backoffice_review','confirmed','refunded')) DEFAULT 'pending',
    provider_ref TEXT,
    confirmed_by_staff_id INTEGER REFERENCES staff(id),
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS point_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id),
    change_amount INTEGER NOT NULL,
    reason TEXT NOT NULL,
    handled_by_staff_id INTEGER REFERENCES staff(id),
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS member_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id),
    note TEXT NOT NULL,
    created_by_staff_id INTEGER REFERENCES staff(id),
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS crm_interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id),
    channel TEXT CHECK(channel IN ('phone','line','email','in_person')) NOT NULL,
    content TEXT,
    created_by_staff_id INTEGER REFERENCES staff(id),
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS complaints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id),
    description TEXT NOT NULL,
    status TEXT CHECK(status IN ('open','in_progress','resolved')) DEFAULT 'open',
    created_by_staff_id INTEGER REFERENCES staff(id),
    created_at TEXT DEFAULT (datetime('now'))
);

-- ============================================================
-- 訂單 / 堂數權益明細帳 / 操作稽核(對照系統分析書 D06/D08/D09/D24)
-- ============================================================

-- 訂單:代表一次「購買行為」,與實際預約/堂數使用分開記錄
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id),
    order_type TEXT CHECK(order_type IN (
        'charter_pass', 'trial', 'self_practice', 'jump', 'japan_trip', 'plan_subscription'
    )) NOT NULL,
    amount INTEGER NOT NULL,
    currency TEXT DEFAULT 'TWD',
    status TEXT CHECK(status IN ('pending', 'paid', 'refunded', 'cancelled')) DEFAULT 'pending',
    ref_type TEXT,          -- 對應到哪一種權益/預約(如 charter_pass、indoor_session)
    ref_id INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

-- 堂數/權益異動明細帳:每一次購買、圈存、解除圈存、正式扣除、退回、人工調整都留一筆紀錄,
-- 會員畫面上的「剩餘堂數」由此明細加總計算,不是只改一個數字
CREATE TABLE IF NOT EXISTS entitlement_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id),
    entitlement_type TEXT CHECK(entitlement_type IN ('charter_pass', 'group_quota')) NOT NULL,
    entitlement_ref_id INTEGER NOT NULL,   -- charter_passes.id 或 member_season_quota_usage 相關的識別
    change_type TEXT CHECK(change_type IN (
        'purchase', 'reserve', 'release', 'deduct', 'refund', 'expire', 'manual_adjust'
    )) NOT NULL,
    amount INTEGER NOT NULL,               -- 正值=增加可用堂數,負值=減少
    order_id INTEGER REFERENCES orders(id),
    booking_ref_type TEXT,                 -- 對應的預約類型(例如 indoor_session)
    booking_ref_id INTEGER,
    staff_id INTEGER REFERENCES staff(id), -- 若為人工調整,記錄操作員工
    note TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- 操作稽核:重要後台操作(價格異動、人工調整堂數、退款、權限查閱)留下前後值與操作人員
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_id INTEGER REFERENCES staff(id),
    action TEXT NOT NULL,
    target_type TEXT,
    target_id INTEGER,
    before_value TEXT,     -- JSON 文字
    after_value TEXT,      -- JSON 文字
    created_at TEXT DEFAULT (datetime('now'))
);

-- 日本滑雪分區種子資料
INSERT INTO japan_regions (code, name, requires_resort_selection, allow_designate_coach, requires_accommodation_option, resort_list_editable, display_order) VALUES
 ('zao', '藏王溫泉滑雪場', 0, 1, 0, 0, 1),
 ('hokkaido', '北海道滑雪場', 1, 1, 0, 0, 2),
 ('onikoube', '鬼首滑雪', 0, 1, 1, 0, 3),
 ('hakuba', '白馬地區滑雪場', 1, 1, 0, 1, 4),
 ('other', '其他雪場', 1, 0, 0, 1, 5);

-- 藏王(免選雪場)自動建立一個對應雪場
INSERT INTO ski_resorts (region_id, code, name)
 SELECT id, 'zao_main', '藏王溫泉滑雪場' FROM japan_regions WHERE code='zao';

-- 北海道:固定5個雪場
INSERT INTO ski_resorts (region_id, code, name)
 SELECT id, 'hokkaido_teine', '手稻滑雪場' FROM japan_regions WHERE code='hokkaido';
INSERT INTO ski_resorts (region_id, code, name)
 SELECT id, 'hokkaido_sapporo_intl', '札幌國際滑雪場' FROM japan_regions WHERE code='hokkaido';
INSERT INTO ski_resorts (region_id, code, name)
 SELECT id, 'hokkaido_asarigawa', '朝里川滑雪場' FROM japan_regions WHERE code='hokkaido';
INSERT INTO ski_resorts (region_id, code, name)
 SELECT id, 'hokkaido_kiroro', 'Kiroro滑雪場' FROM japan_regions WHERE code='hokkaido';
INSERT INTO ski_resorts (region_id, code, name)
 SELECT id, 'hokkaido_onze', 'Onze' FROM japan_regions WHERE code='hokkaido';

-- 鬼首(免選雪場)自動建立一個對應雪場
INSERT INTO ski_resorts (region_id, code, name)
 SELECT id, 'onikoube_main', '鬼首滑雪' FROM japan_regions WHERE code='onikoube';

-- 白馬、其他雪場:雪場清單由後台自行新增,先不建立示範資料
