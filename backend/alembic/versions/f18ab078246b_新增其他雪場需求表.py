"""新增japan_other_resort_requests表:日本滑雪「其他雪場」改為需求提出流程

依你的指示「日本滑雪部份其他雪場這一頁改為其他雪場需求，讓學員提出要求，雪場部份
讓學員自行手動填寫，付款方式拿掉，確認並前往付款改為，向ER Ski提出需求」,把日本
滑雪「其他雪場」這個分區,從原本(比照藏王/北海道/鬼首/白馬)直接走「選雪場→算報價→
選付款方式→建立正式訂單→前往付款」這整套流程,改成單純的「需求提出」:學員自己
打字填想去的雪場名稱跟其他需求說明,送出後不產生訂單、也不會有報價/付款,由ER Ski
後台看到需求後自行跟學員聯繫確認雪場、報價、行程細節。

這是全新的一張表,不是既有japan_bookings的延伸——因為「其他雪場」沒有預先建立的
雪場資料(resort_id)、沒有事先談好的報價(price),硬塞進japan_bookings這種本來
設計給「已知雪場+已知價格+走金流」的資料表並不合適,所以另外建一張輕量的「需求」表,
欄位設計比照既有的charter_pass_requests(會員提出申請、後台審核/處理的既有模式):
status採pending(待處理)/contacted(已聯繫)/closed(已結案)三種狀態,不像
charter_pass_requests有實際的approve/reject金流動作,這裡單純是人工聯繫記錄。

participants(同行人資料)這裡選擇直接存成一個JSON字串欄位,不是沿用既有
booking_participants表(該表的ref_type目前只允許indoor_session_member/
jump_booking/japan_booking三種,這裡不想異動一張正在被實際使用中的表的CHECK
約束,用獨立JSON欄位風險較小、也更簡單)。

這支migration完全是新增資料表,不會動到任何既有資料表或既有資料。

Revision ID: f18ab078246b
Revises: 6e6803c05607
Create Date: 2026-09-21 09:35:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f18ab078246b'
down_revision: Union[str, Sequence[str], None] = '6e6803c05607'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 跟其他migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的text()把SQL裡的
    # 冒號誤判成具名綁定參數)。這支migration只支援PostgreSQL(正式環境),本機SQLite
    # 開發改schema.sql、由init_schema()直接建表,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS japan_other_resort_requests (
            id SERIAL PRIMARY KEY,
            member_id INTEGER NOT NULL REFERENCES members(id),
            resort_name TEXT NOT NULL,       -- 學員自行填寫想去的雪場名稱
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            day_type TEXT CHECK(day_type IN ('half','full')) NOT NULL,
            half_day_slot TEXT CHECK(half_day_slot IN ('morning','afternoon')),
            headcount INTEGER NOT NULL,
            equipment_type TEXT CHECK(equipment_type IN ('ski','snowboard')),
            needs_accommodation INTEGER DEFAULT 0,
            participants TEXT,               -- JSON字串:[{gender,age,height_cm,weight_kg,shoe_size}, ...]
            note TEXT,                        -- 學員填寫的其他需求說明
            status TEXT CHECK(status IN ('pending','contacted','closed')) NOT NULL DEFAULT 'pending',
            handled_by_staff_id INTEGER REFERENCES staff(id),
            staff_note TEXT,
            handled_at TEXT,
            created_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')
        )
    """)

    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    # 故意不砍表:如果已經有學員送出需求(japan_other_resort_requests有資料),
    # 直接砍表會造成資料遺失。如果真的需要復原,請先確認沒有任何需求資料,
    # 再另外手動處理。
    pass
