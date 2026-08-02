import sqlite3
import os
import hashlib

DB_PATH = os.path.join(os.path.dirname(__file__), "erski.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _hash(raw):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


DEMO_STAFF = [
    # work_id, name, display_code, birthday(YYYY-MM-DD), role, branch
    ("0001", "陳老闆", "", "1980-01-01", "boss", "高雄"),
    ("0002", "林主管", "", "1985-02-02", "manager", "高雄"),
    ("0003", "黃客服", "", "1990-03-03", "cs", "高雄"),
    ("0004", "張教練", "甲", "1995-04-04", "coach", "高雄"),
    ("0005", "李教練", "乙", "1996-05-05", "coach", "高雄"),
]


def _seed_demo_staff(conn):
    for work_id, name, code, birthday, role, branch in DEMO_STAFF:
        password = birthday.replace("-", "")[2:8]  # 生日六碼(YYMMDD)
        conn.execute(
            """INSERT OR IGNORE INTO staff
               (work_id, name, display_code, phone, birthday, password_hash, role, branch)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (work_id, name, code, "0900000000", birthday, _hash(password), role, branch),
        )
    # 示範:把甲、乙教練指派到雪場 A(id=1),供日本教練課容量計算測試
    coach_ids = conn.execute(
        "SELECT id FROM staff WHERE work_id IN ('0004','0005')"
    ).fetchall()
    for c in coach_ids:
        conn.execute(
            "INSERT OR IGNORE INTO resort_coaches (resort_id, coach_id) VALUES (1, ?)",
            (c["id"],),
        )


def _seed_zao_coaches(conn):
    """藏王駐站教練團隊完整資料(姓名/證照/駐在地/自我介紹)。"""
    import re
    import hashlib

    CERT_TYPE_MAP = {"CASI": "snowboard", "CSAI": "snowboard", "CSIA": "ski",
                      "PARK": "other", "APSI": "other", "SIA": "other"}

    def parse_certs(cert_str):
        result = []
        for part in cert_str.split("/"):
            part = part.strip()
            if not part:
                continue
            m = re.match(r"([A-Za-z]+)\s+(.*)", part)
            if m:
                cert_name, cert_level = m.group(1), m.group(2)
                cert_type = CERT_TYPE_MAP.get(cert_name.upper(), "other")
                result.append((cert_type, cert_name, cert_level))
        return result

    coaches = [
        {"name": "ALOIS", "certs": "CSIA lv3 Teacher/CASI lv1",
         "resume": "14",
         "experience": "曾擔任北京南山滑雪場教練、加拿大My. Symoure雪場教練、台灣旅行團日本特約教練,駐站北京/張家口/加拿大/美國/新瀉/長野/東北/北海道各大雪場。",
         "quote": "專注細節!創造完美滑行。"},
        {"name": "YUMI", "certs": "CASI Lv2/PARK Lv1/CSIA Lv1",
         "resume": "12",
         "experience": "於2015-16雪季考到教練證照,可中英文雙語教學,並曾擔任滑雪教練資格考試翻譯官。在中國、日本、澳洲都有駐點過,在教學與專業傳遞上都具備國際經驗。擅長以耐心和熱情,讓學生在挑戰中找到樂趣,是一位看到學生達到目標,會比學生更大聲尖叫、更興奮歡呼的教練。",
         "quote": "讓我陪你探索更多可能,寫下專屬於你的雪地故事。Let's ride on! 我們雪上見"},
        {"name": "LACO", "certs": "CASI lv2/PARK lv1/CSIA lv1",
         "resume": "12",
         "experience": "曾擔任台灣旅行團日本特約教練,駐站新瀉/長野/東北/北海道各大雪場,並於期間前往澳洲Perisher skischool擔任滑雪教練。",
         "quote": "滑雪吧!因為沒有比這更可以治癒你。"},
        {"name": "SPIN", "certs": "CASI lv1/CSIA lv1",
         "resume": "10",
         "experience": "曾擔任白馬滑雪學校滑雪駐站教練、台灣旅行團日本特約教練,駐站新瀉/長野/東北/北海道各大雪場。",
         "quote": "練!更多的練習創造成就。"},
        {"name": "Amber", "certs": "CASI Lv2/PARK Lv1/CSIA Lv1",
         "resume": "10",
         "experience": "曾擔任各大雪場駐點教練、CASI翻譯官、ski tour、冰川嚮導等。日本-白馬、妙高、青森、Yuzawa;澳洲-Perisher, Thredbo;北美-Lake Louise, Sunshine, Kicking Horse;中國-北大湖、長白山。身上留著原住民愛冒險的基因,熱愛極限運動,曾用雙腳跑地球一圈、踩著單板19天滑600公里、在8000英尺的冰川上滑雪。",
         "quote": "大山用地形教我滑雪,讓我用地形帶你去看大山的美"},
        {"name": "一路", "certs": "CASI Lv2/APSI Lv1",
         "resume": "8",
         "experience": "曾駐站日本藏王溫泉滑雪場、澳洲Perisher滑雪場擔任滑雪教練。熱愛各式戶外活動,享受自由、喜歡冒險,對於有興趣的事物喜歡專研,善於分析,並融入教學中。",
         "quote": "滑出自由的靈魂,玩出自己的風格"},
        {"name": "MO", "certs": "CASI lv2/CSIA lv1",
         "resume": "6",
         "experience": "曾擔任新疆滑雪團教練、廣州室內雪場駐場教學、日本湯澤雪場、藏王雪場駐站教學。幽默風趣的教學風格,創造快樂的學習氛圍!身為一個Free rider最愛粉雪滑行。",
         "quote": "每趟滑行修正,都是為了邁向更遠的冒險。"},
        {"name": "鋒/IVAN", "certs": "CASI LV1/CSIA lv1",
         "resume": "4",
         "experience": "曾駐站日本藏王溫泉滑雪場擔任滑雪教練。人生半途而廢,目前專職滑雪教練,號稱全團隊最溫柔的教練,擅長細膩的教學、保母級的呵護。",
         "quote": "跌倒了?沒關係,我們準備好再試一次。"},
        {"name": "NITA", "certs": "CASI lv1/CSIA lv1",
         "resume": "7",
         "experience": "曾駐站日本藏王溫泉滑雪場、湯澤區域擔任滑雪教練。熱愛滑行速度,如同風一樣的女子!抱持著熱愛滑雪的心到至今,享受在鬆雪飛翔也喜歡快樂爆衝。夏天在恆春玩海,冬天雪地玩雪,到處探險最快樂!",
         "quote": "滑雪?快樂絕對是一切最重要的事情。"},
        {"name": "SEINA", "certs": "CSIA lv1",
         "resume": "3",
         "experience": "曾駐站日本藏王溫泉滑雪場、宮城鬼首滑雪場、北海道手稻滑雪場擔任滑雪教練。平時是舞蹈老師,冬天雪地教練,從教室地板跳入冰天雪道,享受暢行在雪白世界的美好。",
         "quote": "優雅不僅是形容,更是一種滑行態度。"},
        {"name": "阿用", "certs": "APSI lv1",
         "resume": "4",
         "experience": "曾於日本藏王溫泉滑雪場、宮城鬼首滑雪場擔任滑雪教練。每個人學滑雪的速度不同,而我的工作就是在你懷疑人生之前,把問題找出來。雪地急診室駐診中。",
         "quote": "對症下藥是我們的最高指導原則。"},
        {"name": "NANCY", "certs": "CASI lv2/APSI lv1",
         "resume": "6",
         "experience": "駐站日本藏王溫泉滑雪場、澳洲Falls Creek擔任官方滑雪教練。體育教育出身,曾擔任幼兒體育指導員、中學體育教師及游泳教練,熟悉幼兒至成人教學。",
         "quote": "練在身體與肌肉的記憶,不會背叛你!"},
        {"name": "球球", "certs": "",
         "resume": "4",
         "experience": "長野各大雪場。因為熱愛,所以選擇分享,一路從學習者到教練,更懂得每個人成長路上的辛苦與挑戰,希望透過輕鬆自在的教學方式,陪伴大家建立自信,在雪地裡留下屬於自己的美好回憶。夏天是水球,冬天是雪球。",
         "quote": "享受過程,你會發現自己比想像中更棒!"},
        {"name": "玉米", "certs": "CASI lv2/CSIA lv1",
         "resume": "3",
         "experience": "曾駐站日本藏王溫泉滑雪場擔任滑雪教練。夏天擔任潛水教練,豐富的多年教學經驗,享受單板運動所帶來的流暢滑行體驗。",
         "quote": "風雪中追逐自由,滑雪板下書寫勇敢。"},
        {"name": "Rizz", "certs": "SIA Stage 1/CSIA lv1",
         "resume": "3",
         "experience": "曾於日本輕井澤、苗場、GALA湯澤、神樂及神立等雪場擔任滑雪教練,累積多元雪場與學員教學經驗。熱愛登山、潛水、騎馬等戶外活動,享受探索自然與挑戰自我的過程,擅長將滑雪技巧結合理論式教學,幫助學員理解滑行原理,讓滑行更有深度。",
         "quote": ""},
        {"name": "瑄瑄", "certs": "CASI lv1/CSIA lv1",
         "resume": "3",
         "experience": "長野各大雪場。喜歡用照片與影片,記錄學生每個進步的瞬間,希望能在輕鬆、有趣的教學氛圍中,陪伴大家一步步建立自信、享受滑雪的樂趣。夏天,我在綠島工作與生活,冬天,我們相約在雪上相見。",
         "quote": "嘿~要相信你自己可以做得到!"},
        {"name": "阿傑", "certs": "CSIA lv1",
         "resume": "2",
         "experience": "曾駐湯澤區井澤、苗場、GALA湯澤、神樂及神立等雪場擔任滑雪教練,夏天是潛水教練,歡迎進入白色鴉片世界。",
         "quote": "享受吧!沒有什麼比滑雪當下更重要。"},
        {"name": "菜脯", "certs": "CSIA lv1/CASI lv1",
         "resume": "1",
         "experience": "長野各大雪場。深知初學者的緊張與不安,教學進度因人而異,不論是大人還是小孩,都能在最安全、無壓力的環境下,一邊享受雪景、一邊輕鬆愛上滑雪!",
         "quote": "滑雪不只是運動,更是與自己身體對話的療癒旅程。"},
    ]

    locs = {r["name"]: r["id"] for r in conn.execute("SELECT * FROM coach_location_options")}
    work_id_start = 2001
    for i, c in enumerate(coaches):
        work_id = str(work_id_start + i)
        existing = conn.execute("SELECT id FROM staff WHERE work_id=?", (work_id,)).fetchone()
        if existing:
            continue
        birthday = f"199{i%10}-0{(i%9)+1}-{10+i:02d}"  # 暫時預設生日,請於後台更新為真實資料
        password = birthday.replace("-", "")[2:8]
        cur = conn.execute(
            "INSERT INTO staff (work_id, name, phone, birthday, password_hash, role, branch) VALUES (?, ?, ?, ?, ?, 'coach', ?)",
            (work_id, c["name"], None, birthday, hashlib.sha256(password.encode()).hexdigest(), "日本藏王"),
        )
        staff_id = cur.lastrowid
        conn.execute(
            "INSERT INTO coach_profiles (coach_id, resume, experience, self_intro) VALUES (?, ?, ?, ?)",
            (staff_id, c["resume"], c["experience"], c["quote"]),
        )
        for cert_type, cert_name, cert_level in parse_certs(c["certs"]):
            conn.execute(
                "INSERT INTO coach_certifications (coach_id, cert_type, cert_name, cert_level) VALUES (?, ?, ?, ?)",
                (staff_id, cert_type, cert_name, cert_level),
            )
        # 藏王駐站教練預設指派到藏王溫泉滑雪場,讓客戶端「指定教練」選單一開始就看得到人
        # (其他雪場駐點仍由後台主管視需要手動指派/調整)
        zao_resort = conn.execute("SELECT id FROM ski_resorts WHERE code='zao_main'").fetchone()
        if zao_resort:
            conn.execute(
                "INSERT OR IGNORE INTO resort_coaches (resort_id, coach_id) VALUES (?, ?)",
                (zao_resort["id"], staff_id),
            )


def _seed_demo_bookings(conn):
    """
    示範資料:給ALOIS設定時薪,並建立幾筆測試課程(高雄體驗課x2、日本教練課全日x1),
    方便對照「教練課表/授課時數/計費」實際畫面,拿來參考後續表單管理需要調整什麼。
    """
    alois = conn.execute("SELECT id FROM staff WHERE work_id='2001'").fetchone()
    if not alois:
        return
    alois_id = alois["id"]

    existing_member = conn.execute("SELECT id FROM members WHERE phone='0911111111'").fetchone()
    if existing_member:
        return  # 已經建立過示範資料,不重複建立

    conn.execute(
        """INSERT INTO coach_profiles (coach_id, hourly_rate, updated_at)
           VALUES (?, ?, datetime('now'))
           ON CONFLICT(coach_id) DO UPDATE SET hourly_rate=excluded.hourly_rate, updated_at=datetime('now')""",
        (alois_id, 800),
    )

    cur = conn.execute(
        "INSERT INTO members (name, phone, email, auth_provider) VALUES (?, ?, ?, 'email')",
        ("陳小姐", "0911111111", "demo_chen@example.com"),
    )
    member_id = cur.lastrowid

    for booking_date, start_hour in [("2026-08-15", 14), ("2026-08-18", 10)]:
        cur2 = conn.execute(
            """INSERT INTO indoor_sessions (booking_date, start_hour, duration_minutes, category, coach_id, max_capacity, status)
               VALUES (?, ?, 50, 'trial', ?, 1, 'confirmed')""",
            (booking_date, start_hour, alois_id),
        )
        session_id = cur2.lastrowid
        conn.execute(
            """INSERT INTO indoor_session_members (session_id, member_id, headcount, price, status)
               VALUES (?, ?, 1, 1500, 'enrolled')""",
            (session_id, member_id),
        )

    resort = conn.execute("SELECT id FROM ski_resorts LIMIT 1").fetchone()
    if resort:
        import uuid
        group_key = uuid.uuid4().hex[:12]
        conn.execute(
            """INSERT INTO japan_bookings
               (member_id, resort_id, coach_id, booking_date, day_type, headcount, price, group_key, status)
               VALUES (?, ?, ?, '2026-12-20', 'full', 2, 17500, ?, 'confirmed')""",
            (member_id, resort["id"], alois_id, group_key),
        )


def init_db(reset=False):
    if reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = get_conn()
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    _seed_demo_staff(conn)
    _seed_zao_coaches(conn)
    _seed_demo_bookings(conn)
    conn.commit()
    conn.close()


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db(reset=True)
    print(f"Database initialized at {DB_PATH}")
    print("示範員工帳號(工號 / 密碼 / 角色): "
          "0001/800101/boss、0002/850202/manager、0003/900303/cs、0004/950404/coach")

