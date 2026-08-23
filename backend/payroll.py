"""
教練薪資計算模組
------------
依實際授課紀錄自動計算「堂課/體驗/助教」時數與金額、請假天數與扣款,
其餘人工項目(加班獎金/其他補貼/勞健保/備註)由後台人工填寫或覆蓋。

重要對照假設(如與貴公司實際規則不同,請告知調整):
- 體驗時數 = category='trial' 的室內課程時數
- 堂課時數 = category IN ('charter','self_practice','group_class') 的室內課程時數
             + 日本教練課時數(全日算5小時、半日算3小時)
- 助教時數 = 該教練擔任 assistant_coach_id 的所有場次時數(不分課程種類)
- 請假扣款 = 基本薪資 / 當月天數 × 請假天數(不含例假,因例假本來就不算工作日)
- 勞健保金額:依「基本薪資」對照 insurance_brackets 級距表帶出參考值,
  可在後台「薪資管理」畫面人工覆蓋。此級距表金額僅供試算參考,
  請務必對照勞保局/全民健保署最新公告核對。
"""

import calendar
import os
from datetime import datetime

from db import get_conn, NOW_SQL


def _period_date_range(period):
    """period格式 'YYYY-MM',回傳(該月第一天, 該月最後一天, 該月天數)。"""
    year, month = map(int, period.split("-"))
    last_day = calendar.monthrange(year, month)[1]
    date_from = f"{year:04d}-{month:02d}-01"
    date_to = f"{year:04d}-{month:02d}-{last_day:02d}"
    return date_from, date_to, last_day


def _lookup_insurance(conn, monthly_salary):
    """依月薪金額查詢對照的勞健保員工自付額。找不到落點時,取最接近的級距。"""
    row = conn.execute(
        "SELECT * FROM insurance_brackets WHERE ? >= bracket_min AND ? <= bracket_max",
        (monthly_salary, monthly_salary),
    ).fetchone()
    if row:
        return row["labor_insurance_employee"], row["health_insurance_employee"]
    # 超出級距表範圍(例如薪資高於最高級距),取金額最高的一筆
    row2 = conn.execute("SELECT * FROM insurance_brackets ORDER BY bracket_max DESC LIMIT 1").fetchone()
    if row2:
        return row2["labor_insurance_employee"], row2["health_insurance_employee"]
    return 0, 0


def generate_coach_payroll(coach_id, period, staff_id=None):
    """
    產生(或重新計算)某位教練某個月份的薪資紀錄。
    自動計算的欄位會被覆寫更新;若該筆紀錄已存在,人工填寫過的欄位
    (加班獎金/其他補貼/備註/勞健保如果先前已人工調整過)會保留不動。
    """
    date_from, date_to, days_in_month = _period_date_range(period)
    conn = get_conn()

    profile = conn.execute("SELECT * FROM coach_profiles WHERE coach_id=?", (coach_id,)).fetchone()
    base_salary = profile["base_salary"] if profile and profile["base_salary"] else 0
    rate_group_class = profile["rate_group_class"] if profile and profile["rate_group_class"] else 0
    rate_trial = profile["rate_trial"] if profile and profile["rate_trial"] else 0
    rate_assistant = profile["rate_assistant"] if profile and profile["rate_assistant"] else 0

    # 體驗時數
    trial_minutes = conn.execute(
        """SELECT COALESCE(SUM(duration_minutes), 0) m FROM indoor_sessions
           WHERE coach_id=? AND category='trial' AND status != 'cancelled'
             AND booking_date >= ? AND booking_date <= ?""",
        (coach_id, date_from, date_to),
    ).fetchone()["m"]
    trial_hours = round(trial_minutes / 60, 2)
    trial_amount = round(trial_hours * rate_trial)

    # 堂課時數(包機/自主練習/團課)
    group_minutes = conn.execute(
        """SELECT COALESCE(SUM(duration_minutes), 0) m FROM indoor_sessions
           WHERE coach_id=? AND category IN ('charter','self_practice','group_class') AND status != 'cancelled'
             AND booking_date >= ? AND booking_date <= ?""",
        (coach_id, date_from, date_to),
    ).fetchone()["m"]
    japan_hours = conn.execute(
        """SELECT COALESCE(SUM(CASE WHEN day_type='full' THEN 5 ELSE 3 END), 0) h FROM japan_bookings
           WHERE coach_id=? AND status != 'cancelled'
             AND booking_date >= ? AND booking_date <= ?""",
        (coach_id, date_from, date_to),
    ).fetchone()["h"]
    group_class_hours = round(group_minutes / 60 + japan_hours, 2)
    group_class_amount = round(group_class_hours * rate_group_class)

    # 助教時數
    assistant_minutes = conn.execute(
        """SELECT COALESCE(SUM(duration_minutes), 0) m FROM indoor_sessions
           WHERE assistant_coach_id=? AND status != 'cancelled'
             AND booking_date >= ? AND booking_date <= ?""",
        (coach_id, date_from, date_to),
    ).fetchone()["m"]
    assistant_hours = round(assistant_minutes / 60, 2)
    assistant_amount = round(assistant_hours * rate_assistant)

    # 請假天數(不含例假;例假本來就不算工作日,不在此計算範圍內)
    leave_days = conn.execute(
        """SELECT COUNT(*) c FROM coach_schedule
           WHERE coach_id=? AND status IN ('personal_leave','sick_leave','annual_leave')
             AND work_date >= ? AND work_date <= ?""",
        (coach_id, date_from, date_to),
    ).fetchone()["c"]
    work_days = max(days_in_month - leave_days, 0)
    leave_deduction = round(base_salary / days_in_month * leave_days) if days_in_month and base_salary else 0

    labor_ins, health_ins = _lookup_insurance(conn, base_salary)

    existing = conn.execute(
        "SELECT * FROM coach_payroll_records WHERE coach_id=? AND period=?", (coach_id, period)
    ).fetchone()

    # 人工項目:若已存在紀錄,保留原本人工填寫的值;否則使用預設(勞健保用級距表帶出的參考值)
    overtime_bonus = existing["overtime_bonus"] if existing else 0
    other_subsidy = existing["other_subsidy"] if existing else 0
    other_subsidy_note = existing["other_subsidy_note"] if existing else None
    japan_travel_subsidy = existing["japan_travel_subsidy"] if existing else 0
    japan_transportation_subsidy = existing["japan_transportation_subsidy"] if existing else 0
    labor_insurance = existing["labor_insurance"] if existing else labor_ins
    health_insurance = existing["health_insurance"] if existing else health_ins
    notes = existing["notes"] if existing else None

    net_pay = (
        base_salary - leave_deduction
        + group_class_amount + trial_amount + assistant_amount
        + overtime_bonus + other_subsidy + japan_travel_subsidy + japan_transportation_subsidy
        - labor_insurance - health_insurance
    )

    conn.execute(
        f"""INSERT INTO coach_payroll_records
           (coach_id, period, base_salary, work_days, leave_days, leave_deduction,
            group_class_hours, group_class_amount, trial_hours, trial_amount,
            assistant_hours, assistant_amount, overtime_bonus, other_subsidy, other_subsidy_note,
            japan_travel_subsidy, japan_transportation_subsidy,
            labor_insurance, health_insurance, net_pay, notes, generated_at, confirmed_by_staff_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {NOW_SQL}, ?)
           ON CONFLICT(coach_id, period) DO UPDATE SET
             base_salary=excluded.base_salary, work_days=excluded.work_days, leave_days=excluded.leave_days,
             leave_deduction=excluded.leave_deduction, group_class_hours=excluded.group_class_hours,
             group_class_amount=excluded.group_class_amount, trial_hours=excluded.trial_hours,
             trial_amount=excluded.trial_amount, assistant_hours=excluded.assistant_hours,
             assistant_amount=excluded.assistant_amount, net_pay=excluded.net_pay,
             generated_at={NOW_SQL}, confirmed_by_staff_id=excluded.confirmed_by_staff_id""",
        (coach_id, period, base_salary, work_days, leave_days, leave_deduction,
         group_class_hours, group_class_amount, trial_hours, trial_amount,
         assistant_hours, assistant_amount, overtime_bonus, other_subsidy, other_subsidy_note,
         japan_travel_subsidy, japan_transportation_subsidy,
         labor_insurance, health_insurance, net_pay, notes, staff_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM coach_payroll_records WHERE coach_id=? AND period=?", (coach_id, period)
    ).fetchone()
    conn.close()
    return dict(row)


def update_payroll_manual_fields(record_id, overtime_bonus=None, other_subsidy=None,
                                   other_subsidy_note=None, labor_insurance=None,
                                   health_insurance=None, notes=None,
                                   japan_travel_subsidy=None, japan_transportation_subsidy=None):
    """人工更新加班獎金/其他補貼/日本出差交通補助/勞健保覆蓋值/備註,並重新計算實際所得。"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM coach_payroll_records WHERE id=?", (record_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("找不到此筆薪資紀錄")

    new_overtime = overtime_bonus if overtime_bonus is not None else row["overtime_bonus"]
    new_subsidy = other_subsidy if other_subsidy is not None else row["other_subsidy"]
    new_subsidy_note = other_subsidy_note if other_subsidy_note is not None else row["other_subsidy_note"]
    new_travel = japan_travel_subsidy if japan_travel_subsidy is not None else row["japan_travel_subsidy"]
    new_transport = japan_transportation_subsidy if japan_transportation_subsidy is not None else row["japan_transportation_subsidy"]
    new_labor = labor_insurance if labor_insurance is not None else row["labor_insurance"]
    new_health = health_insurance if health_insurance is not None else row["health_insurance"]
    new_notes = notes if notes is not None else row["notes"]

    net_pay = (
        row["base_salary"] - row["leave_deduction"]
        + row["group_class_amount"] + row["trial_amount"] + row["assistant_amount"]
        + new_overtime + new_subsidy + new_travel + new_transport - new_labor - new_health
    )
    conn.execute(
        """UPDATE coach_payroll_records SET overtime_bonus=?, other_subsidy=?, other_subsidy_note=?,
           japan_travel_subsidy=?, japan_transportation_subsidy=?,
           labor_insurance=?, health_insurance=?, notes=?, net_pay=? WHERE id=?""",
        (new_overtime, new_subsidy, new_subsidy_note, new_travel, new_transport,
         new_labor, new_health, new_notes, net_pay, record_id),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM coach_payroll_records WHERE id=?", (record_id,)).fetchone()
    conn.close()
    return dict(updated)


def get_profit_loss_summary(period):
    """
    月結損益總覽:整合當月營收(訂單/交易)與教練薪資支出,計算淨利。
    period格式 'YYYY-MM'。薪資支出僅計入「已產生薪資紀錄」的教練,
    尚未產生薪資紀錄的教練不會計入支出(建議先在薪資管理分頁產生當月全部教練薪資,再看這份總覽)。
    """
    import booking as booking_module

    date_from, date_to, _ = _period_date_range(period)
    revenue_summary = booking_module.get_report_summary(date_from, date_to)

    conn = get_conn()
    payroll_rows = conn.execute(
        """SELECT pr.*, st.name AS coach_name FROM coach_payroll_records pr
           JOIN staff st ON pr.coach_id = st.id
           WHERE pr.period=?""",
        (period,),
    ).fetchall()
    conn.close()

    total_payroll_expense = sum(r["net_pay"] for r in payroll_rows)
    total_revenue = revenue_summary["total_revenue"]
    net_profit = total_revenue - total_payroll_expense

    return {
        "period": period,
        "total_revenue": total_revenue,
        "revenue_by_type": revenue_summary["revenue_by_type"],
        "total_payroll_expense": total_payroll_expense,
        "payroll_by_coach": [
            {"coach_id": r["coach_id"], "coach_name": r["coach_name"], "net_pay": r["net_pay"]}
            for r in payroll_rows
        ],
        "payroll_generated_count": len(payroll_rows),
        "net_profit": net_profit,
    }


def generate_payslip_pdf(record_id, output_path):
    """依單筆薪資紀錄產生一份正式的薪資單PDF(繁體中文)。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import ParagraphStyle

    if "CJK" not in pdfmetrics.getRegisteredFontNames():
        font_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "wqy-zenhei.ttc")
        pdfmetrics.registerFont(TTFont("CJK", font_path))
    
    conn = get_conn()
    r = conn.execute(
        """SELECT pr.*, st.name AS coach_name, cp.rank AS coach_rank FROM coach_payroll_records pr
           JOIN staff st ON pr.coach_id = st.id
           LEFT JOIN coach_profiles cp ON cp.coach_id = st.id
           WHERE pr.id=?""",
        (record_id,),
    ).fetchone()
    conn.close()
    if not r:
        raise ValueError("找不到此筆薪資紀錄")

    year, month = r["period"].split("-")

    title_style = ParagraphStyle("title", fontName="CJK", fontSize=18, leading=22, alignment=1)
    sub_style = ParagraphStyle("sub", fontName="CJK", fontSize=11, leading=15, alignment=1, textColor=colors.HexColor("#5A6472"))
    section_style = ParagraphStyle("section", fontName="CJK", fontSize=11, leading=15, spaceBefore=10, spaceAfter=4)
    normal_style = ParagraphStyle("normal", fontName="CJK", fontSize=10, leading=14)

    story = [
        Paragraph("ERSKI 滑雪急診室", title_style),
        Paragraph(f"{year}年{int(month)}月　教練薪資單", sub_style),
        Spacer(1, 14),
    ]

    info_data = [
        ["教練姓名", r["coach_name"], "職稱", r["coach_rank"] or "—"],
        ["薪資期間", f"{year}年{int(month)}月", "工作天數", f"{r['work_days']}天"],
    ]
    info_table = Table(info_data, colWidths=[42.5*mm, 42.5*mm, 42.5*mm, 42.5*mm])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "CJK"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F5F7FA")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#F5F7FA")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E6EA")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(info_table)

    story.append(Paragraph("授課明細(依實際課程紀錄自動計算)", section_style))
    course_data = [
        ["項目", "時數", "金額(NT$)"],
        ["堂課(包機/自主練習/團課)", f"{r['group_class_hours']}", f"{r['group_class_amount']:,}"],
        ["體驗課", f"{r['trial_hours']}", f"{r['trial_amount']:,}"],
        ["助教", f"{r['assistant_hours']}", f"{r['assistant_amount']:,}"],
    ]
    course_table = Table(course_data, colWidths=[82*mm, 28*mm, 60*mm])
    course_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "CJK"),
        ("FONTNAME", (0, 0), (-1, 0), "CJK"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E2761")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E6EA")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(course_table)

    story.append(Paragraph("加項與扣項", section_style))
    adj_data = [
        ["項目", "金額(NT$)"],
        ["基本薪資", f"{r['base_salary']:,}"],
        ["加班獎金", f"{r['overtime_bonus']:,}"],
        [f"其他補貼{('('+r['other_subsidy_note']+')') if r['other_subsidy_note'] else ''}", f"{r['other_subsidy']:,}"],
        ["日本出差補助", f"{r['japan_travel_subsidy']:,}"],
        ["日本交通補助", f"{r['japan_transportation_subsidy']:,}"],
        [f"請假扣款(請假{r['leave_days']}天)", f"-{r['leave_deduction']:,}"],
        ["勞保自付額", f"-{r['labor_insurance']:,}"],
        ["健保自付額", f"-{r['health_insurance']:,}"],
    ]
    adj_table = Table(adj_data, colWidths=[110*mm, 60*mm])
    adj_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "CJK"),
        ("FONTNAME", (0, 0), (-1, 0), "CJK"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E2761")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E6EA")),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(adj_table)

    story.append(Spacer(1, 14))
    net_style = ParagraphStyle("net", fontName="CJK", fontSize=16, leading=20, alignment=2, textColor=colors.HexColor("#1E2761"))
    story.append(Paragraph(f"實際所得　NT$ {r['net_pay']:,}", net_style))

    if r["notes"]:
        story.append(Spacer(1, 10))
        story.append(Paragraph(f"備註:{r['notes']}", normal_style))

    doc = SimpleDocTemplate(output_path, pagesize=A4, topMargin=20*mm, bottomMargin=20*mm, leftMargin=20*mm, rightMargin=20*mm)
    doc.build(story)
    return output_path


