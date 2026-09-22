"""新增 TP 營運回寫稽核佇列。

Render/PostgreSQL 是主資料來源。TurboPlus 僅透過受控 API 送出白名單營運操作；
每個 action_id 在資料庫唯一，讓網路重送不會重複確認付款、指派教練或退款。

Revision ID: b0e1c2d3f4a5
Revises: 84f5beee3f57
Create Date: 2026-09-22 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b0e1c2d3f4a5"
down_revision: Union[str, Sequence[str], None] = "84f5beee3f57"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS tp_writeback_actions (
            id SERIAL PRIMARY KEY,
            action_id TEXT NOT NULL UNIQUE,
            action_type TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_source_id TEXT NOT NULL,
            actor_staff_source_id INTEGER NOT NULL REFERENCES staff(id),
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('received', 'applied', 'rejected')),
            result_json TEXT,
            created_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'),
            completed_at TEXT
        )"""
    )
    cursor.execute(
        """CREATE INDEX IF NOT EXISTS idx_tp_writeback_actions_status_created
           ON tp_writeback_actions(status, created_at)"""
    )
    connection.commit()


def downgrade() -> None:
    connection = op.get_bind().connection
    cursor = connection.cursor()
    cursor.execute("DROP TABLE IF EXISTS tp_writeback_actions")
    connection.commit()
