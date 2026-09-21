"""coach_certificate_files加入r2_key欄位,教練照片/證照檔案改存Cloudflare R2

配合這次把教練檔案上傳(宣傳照/證件照/滑雪證照/相關證照/其他證照)改成存放到
Cloudflare R2(物件儲存)、不再整包塞進資料庫的TEXT欄位:

1) 新增r2_key欄位(可為NULL):存放這筆檔案在R2 bucket裡的路徑。R2尚未設定,
   或這筆資料還沒搬過去時,r2_key是NULL,程式會照舊改用file_data欄位裡的內容
   (完全比照改版前的行為,不影響任何現有功能)。

2) file_data欄位原本是NOT NULL,這次拿掉這個限制——檔案成功搬到R2之後,
   file_data會被清空(設為NULL)騰出資料庫空間，避免「資料庫存一份、R2又存一份」
   造成的重複佔用。

這支migration只負責改資料表結構(加欄位、鬆綁NOT NULL），不會主動搬移既有資料
(既有資料的搬移需要實際呼叫Cloudflare R2的API上傳檔案，不適合放在alembic
migration裡執行——網路狀況不穩或R2一時連不上都可能讓正式環境的部署卡住)。
既有資料的搬移改用app.py新增的一支专属API
(POST /api/admin/system/migrate-certificate-files-to-r2，僅限boss角色呼叫)，
部署完成、確認網站正常後再手動觸發一次即可，這支API設計成可以放心重複呼叫。

Revision ID: b75369f060c3
Revises: 9cf25a805f20
Create Date: 2026-09-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b75369f060c3'
down_revision: Union[str, Sequence[str], None] = '9cf25a805f20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('coach_certificate_files', sa.Column('r2_key', sa.Text(), nullable=True))
    op.alter_column('coach_certificate_files', 'file_data', existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError(
        "這支migration把coach_certificate_files.file_data改成可為NULL、並新增了r2_key欄位。"
        "如果已經有檔案被搬到R2(file_data是NULL、r2_key有值),直接還原NOT NULL限制會失敗，"
        "需要先手動確認/處理這些資料列，不提供一鍵downgrade。"
    )
