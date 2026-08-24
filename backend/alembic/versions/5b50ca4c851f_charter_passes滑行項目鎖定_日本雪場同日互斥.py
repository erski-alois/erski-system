"""charter_passes滑行項目鎖定_日本雪場同日互斥

這支migration支援兩項新功能(第二項是純邏輯判斷,不需要改資料庫結構,
所以這支migration實際上只做第一項的欄位異動):
1. 包機堂數包(charter_passes)新增equipment_type欄位,購買堂數包時記錄
   當時選擇的滑行項目(雙板ski/單板snowboard),之後用這張堂數包訂課時,
   一律鎖定使用購買當下記錄的滑行項目,不再讓會員每次訂課時自由更改
   (避免同一張堂數包被混用在不同滑行項目上)。既有(此次上線前)已購買的
   堂數包沒有這個欄位資料,值會是NULL,維持原本可自由選擇滑行項目的舊行為,
   不會影響既有堂數包的使用。
2. 日本教練課新增「同一天不能同時在兩個不同雪場訂課」的限制,純粹是
   book_japan_multi_day()裡的邏輯判斷,不涉及資料表結構異動。

Revision ID: 5b50ca4c851f
Revises: dfba235f22ee
Create Date: 2026-08-23 15:07:25.371370

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5b50ca4c851f'
down_revision: Union[str, Sequence[str], None] = 'dfba235f22ee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_STATEMENTS = [
    "ALTER TABLE charter_passes ADD COLUMN equipment_type TEXT",
]


def upgrade() -> None:
    """Upgrade schema."""
    # 跟前面幾支migration一樣,直接拿底層DBAPI連線執行(避免SQLAlchemy的
    # text()把SQL裡的冒號誤判成具名綁定參數)。這支migration只支援
    # PostgreSQL(正式環境),本機SQLite開發改schema.sql、由init_schema()
    # 直接建表,不會走這支migration。
    connection = op.get_bind().connection
    cursor = connection.cursor()
    for stmt in _UPGRADE_STATEMENTS:
        cursor.execute(stmt)
    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError(
        "這支migration新增的是包機堂數包滑行項目鎖定欄位,"
        "沒有實作一鍵downgrade(避免正式環境誤操作遺失已記錄的滑行項目資料)。"
        "需要回復請手動評估。"
    )
