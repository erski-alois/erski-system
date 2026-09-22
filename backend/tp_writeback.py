"""TurboPlus 營運回寫的 Render 端規則。"""

from __future__ import annotations

import json
from typing import Any

import booking
from db import NOW_SQL


class WritebackError(ValueError):
    """可安全回傳給 TP 操作人員的商業規則錯誤。"""


REFUND_DUAL_APPROVAL_THRESHOLD = 5000
SUPPORTED_ACTIONS = {
    "confirm_pending_payment",
    "assign_indoor_coach",
    "assign_japan_coach",
    "request_refund",
    "approve_refund",
    "reject_refund",
}
_ACTION_LABELS = {
    "confirm_pending_payment": "確認待核對付款",
    "assign_indoor_coach": "指派室內課程教練",
    "assign_japan_coach": "指派日本課程教練",
    "request_refund": "提出退款申請",
    "approve_refund": "核准退款",
    "reject_refund": "駁回退款",
}


def label_for(action_type: str) -> str:
    return _ACTION_LABELS.get(action_type, action_type)


def _as_positive_int(value: Any, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise WritebackError(f"{label}必須是正整數") from exc
    if result <= 0:
        raise WritebackError(f"{label}必須大於 0")
    return result


def _require_actor(conn, staff_source_id: Any, allowed_roles: set[str]) -> dict:
    staff_id = _as_positive_int(staff_source_id, "執行人員來源 ID")
    row = conn.execute(
        "SELECT id, name, work_id, role, is_active FROM staff WHERE id=?",
        (staff_id,),
    ).fetchone()
    if not row or not row["is_active"]:
        raise WritebackError("找不到啟用中的執行人員")
    actor = dict(row)
    if actor["role"] not in allowed_roles:
        raise WritebackError("此執行人員沒有這項營運操作權限")
    return actor


def _audit(conn, staff_id: int, action: str, target_type: str, target_id: int,
           before: dict, after: dict) -> None:
    conn.execute(
        """INSERT INTO audit_log
           (staff_id, action, target_type, target_id, before_value, after_value)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            staff_id, action, target_type, target_id,
            json.dumps(before, ensure_ascii=False, separators=(",", ":")),
            json.dumps(after, ensure_ascii=False, separators=(",", ":")),
        ),
    )


def _confirm_pending_payment(conn, target_source_id: Any, actor: dict) -> dict:
    tx_id = _as_positive_int(target_source_id, "付款來源 ID")
    tx = conn.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
    if not tx:
        raise WritebackError("找不到這筆付款")
    if tx["payment_status"] != "awaiting_backoffice_review":
        raise WritebackError("這筆付款不是待後台核對狀態，不能重複確認")
    conn.execute(
        "UPDATE transactions SET payment_status='confirmed', confirmed_by_staff_id=? WHERE id=?",
        (actor["id"], tx_id),
    )
    if tx["ref_type"] == "charter_order":
        booking.finalize_charter_purchase(tx["ref_id"], conn=conn)
    elif tx["ref_type"] in (
        "indoor_session", "indoor_session_member", "jump_booking", "japan_booking"
    ):
        booking.mark_order_paid(
            tx["ref_type"], tx["ref_id"], conn=conn, payment_method=tx["payment_method"]
        )
    _audit(
        conn, actor["id"], "tp_confirm_payment", "transaction", tx_id,
        {"payment_status": tx["payment_status"]},
        {"payment_status": "confirmed", "channel": "TurboPlus"},
    )
    return {
        "message": "已確認付款，相關訂單與課程權益已依既有規則更新",
        "refresh_entities": ["payments", "orders", "charter_passes", "indoor_sessions",
                             "indoor_session_members", "jump_bookings", "japan_bookings"],
    }


def _validated_coach(conn, coach_source_id: Any, booking_date: str) -> dict:
    coach_id = _as_positive_int(coach_source_id, "指派教練來源 ID")
    coach = conn.execute(
        "SELECT id, name, role, is_active FROM staff WHERE id=?", (coach_id,)
    ).fetchone()
    if not coach:
        raise WritebackError("找不到這位教練")
    if coach["role"] != "coach":
        raise WritebackError("指定人員不是教練身份")
    if not coach["is_active"]:
        raise WritebackError("這位教練目前為非在職狀態")
    leave = booking.check_coach_on_leave(conn, coach_id, booking_date)
    if leave:
        status = booking.COACH_SCHEDULE_STATUS_LABEL.get(leave["status"], leave["status"])
        raise WritebackError(f"這位教練於 {booking_date} 無法上班（{status}）")
    return dict(coach)


def _assign_indoor_coach(conn, target_source_id: Any, payload: dict, actor: dict) -> dict:
    session_id = _as_positive_int(target_source_id, "室內課程來源 ID")
    session = conn.execute(
        "SELECT id, category, coach_id, booking_date, status FROM indoor_sessions WHERE id=?",
        (session_id,),
    ).fetchone()
    if not session:
        raise WritebackError("找不到這堂室內課程")
    if session["category"] not in ("trial", "charter", "group_class"):
        raise WritebackError("這個類別沒有教練指派功能")
    if session["status"] == "cancelled":
        raise WritebackError("這堂課已取消，無法指派教練")
    coach = _validated_coach(conn, payload.get("coach_source_id"), session["booking_date"])
    conn.execute("UPDATE indoor_sessions SET coach_id=? WHERE id=?", (coach["id"], session_id))
    _audit(
        conn, actor["id"], "tp_assign_indoor_coach", "indoor_session", session_id,
        {"coach_id": session["coach_id"]},
        {"coach_id": coach["id"], "channel": "TurboPlus"},
    )
    return {
        "message": "已指派室內課程教練：" + coach["name"],
        "refresh_entities": ["indoor_sessions", "staff", "coach_schedule"],
    }


def _assign_japan_coach(conn, target_source_id: Any, payload: dict, actor: dict) -> dict:
    booking_id = _as_positive_int(target_source_id, "日本課程來源 ID")
    row = conn.execute(
        """SELECT id, coach_id, price, status, attendance_status, booking_date
           FROM japan_bookings WHERE id=?""",
        (booking_id,),
    ).fetchone()
    if not row:
        raise WritebackError("找不到這筆日本課程")
    if row["status"] == "cancelled":
        raise WritebackError("這筆日本課程已取消，無法指派教練")
    if row["attendance_status"] == "completed":
        raise WritebackError("這筆日本課程已完成報到，無法再變更教練")
    coach = _validated_coach(conn, payload.get("coach_source_id"), row["booking_date"])
    profile = conn.execute(
        "SELECT japan_commission_rate FROM coach_profiles WHERE coach_id=?", (coach["id"],)
    ).fetchone()
    commission_rate = (
        profile["japan_commission_rate"] if profile and profile["japan_commission_rate"] else None
    )
    coach_income = round(row["price"] * commission_rate) if commission_rate is not None else None
    conn.execute(
        """UPDATE japan_bookings SET coach_id=?, coach_commission_rate=?, coach_income=?
           WHERE id=?""",
        (coach["id"], commission_rate, coach_income, booking_id),
    )
    _audit(
        conn, actor["id"], "tp_assign_japan_coach", "japan_booking", booking_id,
        {"coach_id": row["coach_id"]},
        {"coach_id": coach["id"], "coach_income": coach_income, "channel": "TurboPlus"},
    )
    return {
        "message": "已指派日本課程教練：" + coach["name"],
        "refresh_entities": ["japan_bookings", "staff", "coach_schedule"],
    }


def _write_refund(conn, order_id: int, order: Any, amount: int, reason: str, actor: dict,
                  requested_by_staff_id: int | None = None) -> tuple[str, int]:
    conn.execute(
        """INSERT INTO transactions
           (member_id, order_id, ref_type, ref_id, amount, payment_type, payment_method,
            payment_status, confirmed_by_staff_id, note)
           VALUES (?, ?, ?, ?, ?, 'refund', 'manual_grant', 'refunded', ?, ?)""",
        (
            order["member_id"], order_id, order["ref_type"], order["ref_id"], amount,
            actor["id"], reason,
        ),
    )
    new_refunded = order["refunded_amount"] + amount
    new_status = "refunded" if new_refunded >= order["paid_amount"] else order["status"]
    conn.execute(
        """UPDATE orders SET refunded_amount=?, status=?,
            pending_refund_amount=NULL, pending_refund_reason=NULL,
            pending_refund_requested_by=NULL, pending_refund_requested_at=NULL
            WHERE id=?""",
        (new_refunded, new_status, order_id),
    )
    after = {"refunded_amount": new_refunded, "reason": reason, "channel": "TurboPlus"}
    if requested_by_staff_id is not None:
        after["requested_by_staff_id"] = requested_by_staff_id
        after["approved_by_staff_id"] = actor["id"]
    _audit(
        conn, actor["id"],
        "tp_refund_approved" if requested_by_staff_id is not None else "tp_refund_order",
        "order", order_id, {"refunded_amount": order["refunded_amount"]}, after,
    )
    return new_status, new_refunded


def _request_refund(conn, target_source_id: Any, payload: dict, actor: dict) -> dict:
    order_id = _as_positive_int(target_source_id, "訂單來源 ID")
    amount = _as_positive_int(payload.get("amount"), "退款金額")
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise WritebackError("退款原因不能空白")
    if len(reason) > 300:
        raise WritebackError("退款原因不能超過 300 字")
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        raise WritebackError("找不到這筆訂單")
    max_refundable = order["paid_amount"] - order["refunded_amount"]
    if amount > max_refundable:
        raise WritebackError("退款金額不合理，最多可退 NT$" + str(max_refundable))
    if order["pending_refund_amount"]:
        raise WritebackError("這筆訂單已有一筆退款申請待核准")
    if amount < REFUND_DUAL_APPROVAL_THRESHOLD:
        status, refunded = _write_refund(conn, order_id, order, amount, reason, actor)
        return {
            "message": "已完成退款 NT$" + str(amount),
            "refund_status": status,
            "refunded_amount": refunded,
            "refresh_entities": ["orders", "payments"],
        }
    conn.execute(
        f"""UPDATE orders SET pending_refund_amount=?, pending_refund_reason=?,
            pending_refund_requested_by=?, pending_refund_requested_at={NOW_SQL} WHERE id=?""",
        (amount, reason, actor["id"], order_id),
    )
    _audit(
        conn, actor["id"], "tp_refund_requested", "order", order_id, {},
        {"pending_refund_amount": amount, "reason": reason, "channel": "TurboPlus"},
    )
    return {
        "message": "退款金額 NT$" + str(amount) + " 已送出，需由另一位股東或老闆核准",
        "refund_status": "pending_approval",
        "refresh_entities": ["orders"],
    }


def _approve_refund(conn, target_source_id: Any, actor: dict) -> dict:
    order_id = _as_positive_int(target_source_id, "訂單來源 ID")
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        raise WritebackError("找不到這筆訂單")
    if not order["pending_refund_amount"]:
        raise WritebackError("這筆訂單目前沒有待核准退款")
    if order["pending_refund_requested_by"] == actor["id"]:
        raise WritebackError("不能核准自己送出的退款申請")
    status, refunded = _write_refund(
        conn, order_id, order, order["pending_refund_amount"],
        order["pending_refund_reason"], actor,
        requested_by_staff_id=order["pending_refund_requested_by"],
    )
    return {
        "message": "已核准並完成退款 NT$" + str(order["pending_refund_amount"]),
        "refund_status": status,
        "refunded_amount": refunded,
        "refresh_entities": ["orders", "payments"],
    }


def _reject_refund(conn, target_source_id: Any, payload: dict, actor: dict) -> dict:
    order_id = _as_positive_int(target_source_id, "訂單來源 ID")
    note = str(payload.get("reason") or "").strip()
    if len(note) > 300:
        raise WritebackError("駁回說明不能超過 300 字")
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        raise WritebackError("找不到這筆訂單")
    if not order["pending_refund_amount"]:
        raise WritebackError("這筆訂單目前沒有待核准退款")
    conn.execute(
        """UPDATE orders SET pending_refund_amount=NULL, pending_refund_reason=NULL,
           pending_refund_requested_by=NULL, pending_refund_requested_at=NULL WHERE id=?""",
        (order_id,),
    )
    _audit(
        conn, actor["id"], "tp_refund_rejected", "order", order_id,
        {"pending_refund_amount": order["pending_refund_amount"],
         "requested_by_staff_id": order["pending_refund_requested_by"]},
        {"rejection_note": note, "channel": "TurboPlus"},
    )
    return {"message": "已駁回退款申請", "refresh_entities": ["orders"]}


def apply_action(conn, action_type: Any, target_source_id: Any, actor_staff_source_id: Any,
                 payload: Any) -> dict:
    action_type = str(action_type or "").strip()
    if action_type not in SUPPORTED_ACTIONS:
        raise WritebackError("不支援的營運操作類型")
    if not isinstance(payload, dict):
        raise WritebackError("操作資料格式不正確")
    if action_type == "confirm_pending_payment":
        actor = _require_actor(conn, actor_staff_source_id, {"cs", "manager", "boss"})
        return _confirm_pending_payment(conn, target_source_id, actor)
    if action_type == "assign_indoor_coach":
        actor = _require_actor(conn, actor_staff_source_id, {"cs", "boss"})
        return _assign_indoor_coach(conn, target_source_id, payload, actor)
    if action_type == "assign_japan_coach":
        actor = _require_actor(conn, actor_staff_source_id, {"cs", "boss"})
        return _assign_japan_coach(conn, target_source_id, payload, actor)
    if action_type == "request_refund":
        actor = _require_actor(conn, actor_staff_source_id, {"cs", "boss"})
        return _request_refund(conn, target_source_id, payload, actor)
    if action_type == "approve_refund":
        actor = _require_actor(conn, actor_staff_source_id, {"cs", "boss"})
        return _approve_refund(conn, target_source_id, actor)
    actor = _require_actor(conn, actor_staff_source_id, {"cs", "boss"})
    return _reject_refund(conn, target_source_id, payload, actor)
