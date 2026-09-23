"""員工Andy從主管改為股東身份;主管新增合作單位/教練指派管理權限

依你的指示:
1.「股東再增加Andy」——資料庫裡work_id=C0002這筆Andy的staff帳號原本是
  role=manager(主管),這次要改成role=cs(股東)。不是新增一筆新帳號,是把
  既有這筆的身份改掉,避免同一個人有兩個角色重複的帳號。
2.「主管是小于和lili」——role=manager裡本來就已經有小于(work_id=C0003)、
  Lili(work_id=C0006)這兩筆(還有既有的林主管測試帳號、慈慈這兩筆,這次
  你確認慈慈的主管身份維持不動,所以這裡不用動資料),不需要額外新增。
3.「主管權限增加合作單位、教練指派管理」——這是app.py/index.html裡
  SECTION_ROLES的程式碼權限設定變更,已經在同一次改版的程式碼裡處理過
  (partners、groupassign兩個分頁加入manager),不是這支migration要做的事,
  這支migration只處理上面第1點的資料異動。

用work_id比對(比對id數字更穩,work_id在staff表是這套帳號體系裡人工賦予的
穩定代碼)。天生冪等:如果已經被改成cs或這筆work_id不存在了,UPDATE影響
0筆,重複套用不會出錯。

Revision ID: d3f7a2c58b91
Revises: 3e2b537bca1e
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd3f7a2c58b91'
down_revision: Union[str, Sequence[str], None] = '3e2b537bca1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE staff SET role=%s WHERE work_id=%s AND role=%s",
        ('cs', 'C0002', 'manager'),
    )
    connection.commit()


def downgrade() -> None:
    """Downgrade schema."""
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute(
        "UPDATE staff SET role=%s WHERE work_id=%s AND role=%s",
        ('manager', 'C0002', 'cs'),
    )
    connection.commit()
