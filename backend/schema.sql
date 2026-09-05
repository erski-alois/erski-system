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
    auth_provider TEXT CHECK(auth_provider IN ('line','google','apple','email')) NOT NULL,
    password_hash TEXT,   -- 會員登入密碼(僅email/apple/google等以email識別的登入方式使用)
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
    referral_code TEXT,                    -- 首次填寫的優惠碼(填過後不可再自行更改)
    referral_partner_id INTEGER REFERENCES partner_organizations(id),
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
    id_number TEXT,                     -- 身分證字號
    address TEXT,                       -- 地址
    nickname TEXT,                      -- 暱稱
    email TEXT,                         -- email(純聯絡資訊用,不是登入帳號,無UNIQUE限制)
    line_id TEXT,                       -- LINE(純聯絡資訊用,跟members.line_user_id那種OAuth登入識別欄位不同)
    instagram TEXT,                     -- IG
    facebook TEXT,                      -- FB
    password_hash TEXT NOT NULL,
    role TEXT CHECK(role IN ('coach','cs','manager','boss')) NOT NULL,
    branch TEXT NOT NULL,
    is_coach BOOLEAN DEFAULT 1,
    is_active BOOLEAN DEFAULT 1,   -- 軟刪除用:停用後不會出現在教練清單,但保留歷史預約/稽核紀錄的關聯
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
    assistant_coach_id INTEGER REFERENCES staff(id),  -- 助教(協助主教練上課),薪資另計助教時薪
    max_capacity INTEGER NOT NULL DEFAULT 4,
    status TEXT CHECK(status IN (
        'pending_payment','open','confirmed','needs_manual_review','cancelled'
    )) DEFAULT 'pending_payment',
    charter_package_size INTEGER,
    designate_fee INTEGER NOT NULL DEFAULT 0,  -- 會員自選教練時加收的指定費(比照日本滑雪機制,金額來自pricing_config,目前只記錄金額,實際收款由客服後台手動處理)
    attendance_status TEXT CHECK(attendance_status IN ('pending','completed','no_show')) DEFAULT 'pending',
    lesson_notes TEXT,               -- 教練評估/教學內容/異常記錄
    checked_in_at TEXT,
    checked_in_by_staff_id INTEGER REFERENCES staff(id),
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
    attendance_status TEXT CHECK(attendance_status IN ('pending','completed','no_show')) DEFAULT 'pending',
    lesson_notes TEXT,
    checked_in_at TEXT,
    checked_in_by_staff_id INTEGER REFERENCES staff(id),
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS charter_passes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id),
    package_size INTEGER NOT NULL,
    headcount_type INTEGER NOT NULL,
    remaining INTEGER NOT NULL,
    equipment_type TEXT,   -- 購買當下選擇的滑行項目(ski/snowboard),之後用這張堂數包訂課一律鎖定此項目;
                           -- 此功能上線前已購買的舊堂數包這欄是NULL,維持原本可自由選擇滑行項目的行為
    created_at TEXT DEFAULT (datetime('now'))
);

-- 會員對已購買的包機堂數包提出「取消」或「換堂數包大小」申請,退不退款、
-- 換多少堂由客服後台審核決定(不自動執行金流),對應規則書的相關要求。
CREATE TABLE IF NOT EXISTS charter_pass_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    charter_pass_id INTEGER NOT NULL REFERENCES charter_passes(id),
    member_id INTEGER NOT NULL REFERENCES members(id),
    request_type TEXT CHECK(request_type IN ('cancel','resize')) NOT NULL,
    requested_package_size INTEGER,   -- 只有resize才有值,會員希望改成的新堂數包大小
    note TEXT,
    status TEXT CHECK(status IN ('pending','approved','rejected')) NOT NULL DEFAULT 'pending',
    handled_by_staff_id INTEGER REFERENCES staff(id),
    handled_at TEXT,
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
    designate_fee INTEGER DEFAULT 0,        -- 指定教練加收費用(有指定教練固定+1000)
    needs_accommodation BOOLEAN DEFAULT 0,
    price INTEGER NOT NULL,
    group_key TEXT,                          -- 群組名稱(可由後台點選共用班表日曆自動產生,或手動輸入)
    payment_plan TEXT CHECK(payment_plan IN ('full','deposit')) DEFAULT 'full',
    deposit_amount INTEGER DEFAULT 0,
    deposit_paid BOOLEAN DEFAULT 0,
    deposit_paid_date TEXT,
    deposit_payment_method TEXT,
    balance_amount INTEGER DEFAULT 0,
    balance_paid BOOLEAN DEFAULT 0,
    balance_paid_date TEXT,
    balance_payment_method TEXT,
    balance_collected_by_staff_id INTEGER REFERENCES staff(id),
    coach_commission_rate REAL,             -- 該筆訂單套用的教練提成比例(自動帶入教練個人設定)
    coach_income INTEGER,                   -- 自動計算 = price(扣除退佣後) * coach_commission_rate
    rebate_partner_id INTEGER REFERENCES partner_organizations(id),  -- 退佣對象(合作單位)
    rebate_amount INTEGER DEFAULT 0,
    rebate_date TEXT,
    referral_form TEXT,                      -- 轉介單(老闆手動填)
    referral_fee INTEGER DEFAULT 0,          -- 轉介費用(老闆手動填)
    referral_target TEXT,                    -- 轉介對象(老闆手動填)
    status TEXT CHECK(status IN ('pending_payment','confirmed','cancelled')) DEFAULT 'pending_payment',
    attendance_status TEXT CHECK(attendance_status IN ('pending','completed','no_show')) DEFAULT 'pending',
    lesson_notes TEXT,
    checked_in_at TEXT,
    checked_in_by_staff_id INTEGER REFERENCES staff(id),
    created_at TEXT DEFAULT (datetime('now'))
);

-- 上課碼/下課碼(2026-09新增):日本教練課訂單付款確認後自動產生,供教練頁面輸入
-- 學員提供的編碼以完成報到。半天課程產生1組(session_slot對應half_day_slot);
-- 全天課程產生2組(morning+afternoon各一組);多天課程則是每一天(各自一筆
-- japan_bookings)各自依上述規則產生,見 booking.py 的 _create_japan_attendance_codes。
CREATE TABLE IF NOT EXISTS attendance_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_type TEXT CHECK(ref_type IN ('japan_booking')) NOT NULL,
    ref_id INTEGER NOT NULL,          -- 對應到japan_bookings.id,無外鍵約束(比照booking_participants慣例)
    session_date TEXT NOT NULL,       -- 上課當天日期(=該筆japan_bookings.booking_date)
    session_slot TEXT CHECK(session_slot IN ('morning','afternoon')) NOT NULL,
    checkin_code TEXT NOT NULL,       -- 8碼亂數,全表不重複
    checkout_code TEXT NOT NULL,      -- 8碼亂數,全表不重複
    checkin_used_at TEXT,
    checkin_verified_by_staff_id INTEGER REFERENCES staff(id),
    checkout_used_at TEXT,
    checkout_verified_by_staff_id INTEGER REFERENCES staff(id),
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(ref_type, ref_id, session_slot)
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

-- 合作單位(可產生優惠碼給客戶填寫,用於後續匯出資料計算回饋/回扣)
CREATE TABLE IF NOT EXISTS partner_organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    contact_name TEXT,
    contact_phone TEXT,
    contact_email TEXT,
    code TEXT UNIQUE NOT NULL,
    rebate_rate REAL DEFAULT 0,   -- 回饋比例(例如 0.05 代表 5%)
    is_active BOOLEAN DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

-- 價格設定(後台可調整,取代原本寫死在程式碼裡的價格常數)
CREATE TABLE IF NOT EXISTS pricing_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_key TEXT UNIQUE NOT NULL,
    config_value TEXT NOT NULL,   -- JSON格式
    label TEXT,                   -- 後台顯示用的說明文字
    updated_at TEXT DEFAULT (datetime('now')),
    updated_by_staff_id INTEGER REFERENCES staff(id)
);

-- 設備項目(機台/跳台等)
CREATE TABLE IF NOT EXISTS equipment_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    equipment_type TEXT CHECK(equipment_type IN ('machine','jump_platform','other')) NOT NULL,
    status TEXT CHECK(status IN ('active','maintenance','out_of_service')) DEFAULT 'active',
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- 設備保養/故障/事故紀錄(含每日檢查、保養、故障停機、事故)
CREATE TABLE IF NOT EXISTS equipment_maintenance_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id INTEGER NOT NULL REFERENCES equipment_items(id),
    log_type TEXT CHECK(log_type IN ('daily_check','maintenance','breakdown','incident')) NOT NULL,
    description TEXT,
    photo TEXT,           -- base64圖片,選填
    status TEXT CHECK(status IN ('open','resolved')) DEFAULT 'open',
    resolved_at TEXT,
    resolution_note TEXT,  -- 改善追蹤紀錄
    staff_id INTEGER REFERENCES staff(id),
    created_at TEXT DEFAULT (datetime('now'))
);

-- 設備停用日期(維修/故障期間阻擋該設備對應資源的新預約)
CREATE TABLE IF NOT EXISTS equipment_closures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipment_id INTEGER NOT NULL REFERENCES equipment_items(id),
    closure_date TEXT NOT NULL,
    reason TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- 簡易FAQ客服機器人:問答知識庫(關鍵字比對)
CREATE TABLE IF NOT EXISTS faq_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    keywords TEXT,        -- 逗號分隔的關鍵字,用於比對客戶輸入的問題
    category TEXT,
    is_active BOOLEAN DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

-- FAQ無法回答的問題紀錄(供客服後續人工處理,對照系統分析書「無法回答即建立案件」控制點)
CREATE TABLE IF NOT EXISTS faq_unanswered_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER REFERENCES members(id),
    question_text TEXT NOT NULL,
    status TEXT CHECK(status IN ('pending','resolved')) DEFAULT 'pending',
    resolved_by_staff_id INTEGER REFERENCES staff(id),
    resolution_note TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- 常用同行人(會員可儲存常用的同行學員資料,預約時直接選取重複使用)
CREATE TABLE IF NOT EXISTS member_companions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id),
    name TEXT,
    gender TEXT CHECK(gender IN ('male','female')),
    age INTEGER,
    height_cm REAL,
    weight_kg REAL,
    shoe_size TEXT,
    equipment_type TEXT CHECK(equipment_type IN ('ski','snowboard')),
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

-- 教練團隊個人檔案(宣傳照/自我介紹/證件照/合約類型/職級)
CREATE TABLE IF NOT EXISTS coach_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coach_id INTEGER UNIQUE NOT NULL REFERENCES staff(id),
    promo_photo TEXT,      -- base64 圖片資料
    id_photo TEXT,         -- base64 圖片資料(證件照,內部使用)
    self_intro TEXT,       -- 舊版「自我介紹/給學員的一句話」合併欄位,2026-08新增下面三個獨立欄位後保留不動、不搬移資料
    contract_type TEXT CHECK(contract_type IN ('japan_short_term','taiwan_full_time','taiwan_part_time','contract_unit')),
    rank TEXT,             -- 職稱:主管/訓練官/教練
    hourly_rate INTEGER,   -- 教練時薪/鐘點費率(用於估算授課費用)
    resume TEXT,           -- 資歷/教學年資(年資數字,例如"12",顯示為"12年")
    experience TEXT,       -- 經歷/教學經歷(曾任職雪場/單位等敘述)
    years_of_service INTEGER,  -- 年資(由管理者填寫,人事用途,與上面對外顯示的resume分開)
    contract_year TEXT,        -- 合約年(由管理者填寫)
    discipline TEXT CHECK(discipline IN ('ski','snowboard','both')),  -- 滑行項目
    specialty TEXT,             -- 滑行專長
    snow_years INTEGER,         -- 雪齡
    other_experience TEXT,      -- 其他相關經歷(跟上面experience「曾任職雪場/單位」分開)
    bio_intro TEXT,             -- 自我介紹(前端限制30字內)
    message_to_students TEXT,   -- 給學員一句話(前端限制30字內)
    coach_motto TEXT,           -- 代表教練一句話(前端限制30字內)
    base_salary INTEGER,           -- 基本薪資(底薪,僅主管可見/設定)
    rate_group_class INTEGER,      -- 堂課時薪(包機/自主練習/團課,依實際授課時數計算)
    rate_trial INTEGER,            -- 體驗課時薪
    rate_assistant INTEGER,        -- 助教時薪(協助主教練上課)
    japan_commission_rate REAL,    -- 日本教練課個人抽成比例(例如0.9代表報價的90%歸教練),各教練不同
    updated_at TEXT DEFAULT (datetime('now'))
);

-- 教練能力選項清單(可由主管新增選項,例如 Examiner/Trainer/Ski/Snowboard/Others)
-- 勞保/健保投保級距對照表(僅供計算參考!請務必對照勞保局/全民健保署最新公告級距表確認金額)
CREATE TABLE IF NOT EXISTS insurance_brackets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bracket_min INTEGER NOT NULL,          -- 月薪下限(含)
    bracket_max INTEGER NOT NULL,          -- 月薪上限(含)
    insured_salary INTEGER NOT NULL,       -- 對應投保薪資(級距金額)
    labor_insurance_employee INTEGER NOT NULL,   -- 勞保員工自付額(普通事故20%部分)
    health_insurance_employee INTEGER NOT NULL,  -- 健保員工自付額(本人,不含眷屬加成)
    created_at TEXT DEFAULT (datetime('now'))
);

-- 教練每月薪資紀錄(依實際授課時數自動計算堂課/體驗/助教金額,其餘人工項目手動填寫)
CREATE TABLE IF NOT EXISTS coach_payroll_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coach_id INTEGER NOT NULL REFERENCES staff(id),
    period TEXT NOT NULL,                  -- 月份,格式 YYYY-MM
    base_salary INTEGER DEFAULT 0,
    work_days INTEGER DEFAULT 0,           -- 自動計算:當月天數 - 請假天數(不含例假)
    leave_days INTEGER DEFAULT 0,          -- 當月請假天數(自動計算,不含例假)
    leave_deduction INTEGER DEFAULT 0,     -- 自動計算:請假當天不發薪的扣款金額
    group_class_hours REAL DEFAULT 0,      -- 自動計算(包機+自主練習+團課+日本教練課時數)
    group_class_amount INTEGER DEFAULT 0,
    trial_hours REAL DEFAULT 0,            -- 自動計算(體驗課時數)
    trial_amount INTEGER DEFAULT 0,
    assistant_hours REAL DEFAULT 0,        -- 自動計算(擔任助教的時數)
    assistant_amount INTEGER DEFAULT 0,
    overtime_bonus INTEGER DEFAULT 0,      -- 人工填寫
    other_subsidy INTEGER DEFAULT 0,       -- 人工填寫(例如Wax耗材補貼)
    other_subsidy_note TEXT,
    japan_travel_subsidy INTEGER DEFAULT 0,        -- 日本出差補助(依當月實際發生次數手動填寫)
    japan_transportation_subsidy INTEGER DEFAULT 0, -- 日本交通補助(依當月實際發生次數手動填寫)
    labor_insurance INTEGER DEFAULT 0,     -- 可由級距表自動帶入,亦可人工覆蓋
    health_insurance INTEGER DEFAULT 0,
    net_pay INTEGER DEFAULT 0,             -- 自動加總計算之實際所得
    notes TEXT,                            -- 備註
    generated_at TEXT DEFAULT (datetime('now')),
    confirmed_by_staff_id INTEGER REFERENCES staff(id),
    UNIQUE(coach_id, period)
);

-- 日本教練課議價紀錄(後台專用工具,記錄客製化議價/現場成交的日本教練課,不影響前台既有固定表訂課流程)

CREATE TABLE IF NOT EXISTS coach_capability_options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);

-- 教練能力(教練與能力選項的關聯,可複選)
CREATE TABLE IF NOT EXISTS coach_capabilities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coach_id INTEGER NOT NULL REFERENCES staff(id),
    capability_option_id INTEGER NOT NULL REFERENCES coach_capability_options(id),
    UNIQUE(coach_id, capability_option_id)
);

-- 教練證照(證照別+證照名稱+證照等級,可新增多筆)
CREATE TABLE IF NOT EXISTS coach_certifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coach_id INTEGER NOT NULL REFERENCES staff(id),
    cert_type TEXT CHECK(cert_type IN ('ski','snowboard','other')) NOT NULL,
    cert_name TEXT,
    cert_level TEXT NOT NULL
);

-- 教練證照「檔案」上傳(滑雪證照/相關證照/其他證照,每一類都可上傳多筆,圖片或PDF都收,
-- 做法比照coach_profiles.promo_photo/id_photo,直接把檔案內容以base64存進TEXT欄位)
CREATE TABLE IF NOT EXISTS coach_certificate_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coach_id INTEGER NOT NULL REFERENCES staff(id),
    category TEXT CHECK(category IN ('ski_license','related_license','other_license')) NOT NULL,
    file_name TEXT,
    mime_type TEXT,
    file_data TEXT NOT NULL,   -- base64(含data URI前綴)
    uploaded_at TEXT DEFAULT (datetime('now'))
);

-- 教練駐在地選項清單(可由主管新增選項)
CREATE TABLE IF NOT EXISTS coach_location_options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    is_indoor_branch INTEGER NOT NULL DEFAULT 0  -- 是否為室內滑雪分店(1)或日本雪場(0),決定前台包機「指定教練」下拉選單要抓哪些教練
);

-- 教練駐在地(教練與駐在地選項的關聯,可複選)
CREATE TABLE IF NOT EXISTS coach_locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coach_id INTEGER NOT NULL REFERENCES staff(id),
    location_option_id INTEGER NOT NULL REFERENCES coach_location_options(id),
    UNIQUE(coach_id, location_option_id)
);

-- ============================================================
-- 交易 / 付款 / CRM
-- ============================================================

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id INTEGER NOT NULL REFERENCES members(id),
    order_id INTEGER REFERENCES orders(id),   -- 直接關聯訂單(支援訂金/尾款/退款分次記錄)
    ref_type TEXT,
    ref_id INTEGER,
    amount INTEGER NOT NULL,
    payment_type TEXT CHECK(payment_type IN ('full','deposit','balance','refund')) DEFAULT 'full',
    payment_method TEXT CHECK(payment_method IN ('online_card','onsite','bank_transfer','manual_grant','webatm','atm')),
    payment_status TEXT CHECK(payment_status IN ('pending','awaiting_backoffice_review','confirmed','refunded')) DEFAULT 'pending',
    provider_ref TEXT,     -- 我們自己產生的訂單編號(綠界叫MerchantTradeNo)
    ecpay_trade_no TEXT,   -- 綠界自己的交易編號(TradeNo,ReturnURL回調帶回來的)
    atm_bank_code TEXT,          -- ATM櫃員機付款:銀行代碼
    atm_virtual_account TEXT,    -- ATM櫃員機付款:虛擬帳號
    atm_expire_date TEXT,        -- ATM櫃員機付款:繳費期限
    confirmed_by_staff_id INTEGER REFERENCES staff(id),
    note TEXT,
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
    discount_amount INTEGER DEFAULT 0,      -- 客服/主管後台核准的折扣金額
    paid_amount INTEGER DEFAULT 0,          -- 累計已收款金額(可分次收,支援訂金/尾款)
    refunded_amount INTEGER DEFAULT 0,      -- 累計已退款金額
    currency TEXT DEFAULT 'TWD',
    status TEXT CHECK(status IN ('pending', 'paid', 'refunded', 'cancelled')) DEFAULT 'pending',
    ref_type TEXT,          -- 對應到哪一種權益/預約(如 charter_pass、indoor_session)
    ref_id INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    -- 2026-08新增:退款金額達NT$5,000以上時的雙重核准機制(見規則書)。
    -- 同一時間一筆訂單最多只有一筆待核准的退款申請;送出申請的主管不能自己核准。
    pending_refund_amount INTEGER,            -- 待核准的退款金額,NULL表示目前沒有待審核申請
    pending_refund_reason TEXT,               -- 申請退款時填寫的原因
    pending_refund_requested_by INTEGER REFERENCES staff(id),  -- 送出申請的員工
    pending_refund_requested_at TEXT
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

-- 教練駐在地選項種子資料(高雄是室內滑雪分店,其餘是日本雪場)
INSERT INTO coach_location_options (name, is_indoor_branch) VALUES
 ('藏王', 0), ('鬼首', 0), ('北海道', 0), ('高雄', 1), ('其他', 0);

-- 教練能力選項種子資料(中英並列顯示)
INSERT INTO coach_capability_options (name) VALUES
 ('Examiner(考官)'), ('Trainer(訓練官)'), ('Ski(雙板)'), ('Snowboard(單板)'), ('雙棲'), ('Others(其他)');

-- 價格設定種子資料(對應原本寫死在pricing.py的預設值,行為不變)
INSERT INTO pricing_config (config_key, config_value, label) VALUES
 ('trial_price', '{"1":1500,"2":2500,"3":3500,"4":4500}', '體驗課價格(依人數1~4人)'),
 ('charter_price', '{"5":{"1":8500,"2":13000},"10":{"1":16000,"2":24000}}', '包機堂數包價格(堂數5或10 x 對戰人數1或2)'),
 ('self_practice_price', '{"30":300,"60":500,"120":800}', '自主練習價格(依時長分鐘)'),
 ('jump_price', '{"60":300,"120":500}', '跳台體驗價格(依時長分鐘)'),
 ('group_class_price', 'null', '團課額外收費(null代表不額外收費,算會員資格內)'),
 ('japan_full_day_price', '{"1":15000,"2":16500,"3":18000,"4":19500}', '日本教練課全日價格(依人數1~4人)'),
 ('japan_half_day_price', '{"1":11000,"2":12000,"3":13000,"4":14000}', '日本教練課半日價格(依人數1~4人)'),
 ('japan_coach_designate_fee', '1000', '日本教練課指定教練加收費用'),
 ('charter_coach_designate_fee', '500', '室內滑雪包機指定教練加收費用'),
 ('group_class_min', '2', '團課最低成班人數'),
 ('group_class_max', '4', '團課最大人數(額滿截止報名)'),
 ('plan_fee', '{"A":{"enrollment_fee":2500,"monthly":1500,"annual":18000},"B":{"enrollment_fee":3500,"monthly":2500,"annual":30000}}', 'A/B方案入會費(一次性)/月費/年繳(=月費x12,一次繳完12個月)'),
 ('plan_quota', '{"A":{"summer":{"charter":2,"self_practice":1,"group_class":2},"winter":{"charter":1,"self_practice":1,"group_class":1}},"B":{"summer":{"charter":3,"self_practice":2,"group_class":3},"winter":{"charter":2,"self_practice":1,"group_class":2}}}', 'A/B方案每月額度(夏季4-9月/冬季10-3月)'),
 ('indoor_start_hour', '10', '室內滑雪機台每日開始營業時間(整點)'),
 ('indoor_last_start_hour', '20', '室內滑雪機台每日最後一堂開課時間(整點)'),
 ('min_advance_booking_hours', '2', '當天課程最少須提前幾小時預約'),
 ('booking_window_days', '30', '體驗/自主練習/團課開放未來幾天內預約');

-- FAQ示範資料
INSERT INTO faq_entries (question, answer, keywords, category) VALUES
 ('營業時間是幾點到幾點?', '室內滑雪機台營業時間為每日10:00~21:00,最後一堂開課時間為20:00(20:00-20:50)。', '營業時間,幾點,開門,幾點關', '營運'),
 ('體驗課可以訂幾次?', '體驗課依裝備類型(雙板/單板)各限購一次,若想繼續上課建議購買包機堂數包。', '體驗課,次數,幾次,限購', '課程'),
 ('包機堂數包多久到期?', '包機堂數包沒有使用期限,可依需求分次預約使用,但建議儘早使用完畢以確保教練排班順暢。', '堂數包,到期,期限,過期', '課程'),
 ('如何取消或修改預約?', '室內滑雪課程開課前3天內、日本教練課開課前1個月內,系統不開放自行取消/修改,請洽客服協助處理;超過此期限可直接在對應課程頁面的時段上操作。', '取消,修改,改期,退課', '預約'),
 ('日本教練課什麼時候開放預約?', '日本教練課固定每年12月至隔年4月為雪季開放預約,其餘月份不開放。', '日本,雪季,開放,幾月', '日本教練課'),
 ('團課怎麼報名?', '團課需先申請A/B方案並經客服審核通過後才能報名,報名時滿2人即可成班,滿4人截止報名。', '團課,報名,方案,成班', '課程');

-- 設備種子資料(對應目前系統的機台與跳台資源)
INSERT INTO equipment_items (name, equipment_type, status) VALUES
 ('室內滑雪機台', 'machine', 'active'),
 ('跳台', 'jump_platform', 'active');

-- 勞健保投保級距種子資料(僅供試算參考!請務必對照勞保局/健保署最新公告級距表核對後修正)
INSERT INTO insurance_brackets (bracket_min, bracket_max, insured_salary, labor_insurance_employee, health_insurance_employee) VALUES
 (0, 27470, 27470, 549, 372),
 (27471, 30300, 30300, 606, 410),
 (30301, 31800, 31800, 636, 431),
 (31801, 33300, 33300, 666, 451),
 (33301, 34800, 34800, 696, 471),
 (34801, 36300, 36300, 726, 491),
 (36301, 38200, 38200, 764, 517),
 (38201, 40100, 40100, 802, 543),
 (40101, 42000, 42000, 840, 569),
 (42001, 43900, 43900, 878, 594);
