"""College-style landscape PDF of a generated timetable."""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from .services import school_sheet_context


NAVY = colors.HexColor('#1a2332')
LINE = colors.HexColor('#222222')
BREAK_BG = colors.HexColor('#eeeeee')
SPORT_BG = colors.HexColor('#fff8dc')
HEAD_BG = colors.HexColor('#e8eef5')


def _time_header(slot):
    return f'{slot.start_time.strftime("%H:%M")}-{slot.end_time.strftime("%H:%M")}'


def _draw_vtext(c, text, x, y, height, font='Helvetica-Bold', size=7):
    c.saveState()
    c.setFont(font, size)
    c.translate(x, y + height / 2.0)
    c.rotate(90)
    c.drawCentredString(0, -2, text)
    c.restoreState()


def _draw_cell_text(c, text, cx, cy, w, h):
    if not text:
        return
    parts = text.split('/')
    c.setFillColor(NAVY)
    if len(text) > 16 and len(parts) > 1:
        mid = (len(parts) + 1) // 2
        line1 = '/'.join(parts[:mid])
        line2 = '/'.join(parts[mid:])
        c.setFont('Helvetica-Bold', 5)
        c.drawCentredString(cx + w / 2, cy + h / 2 + 2, line1[:22])
        c.drawCentredString(cx + w / 2, cy + h / 2 - 5, line2[:22])
        return
    size = 5.0 if len(text) > 16 else 6.0 if len(text) > 10 else 6.5
    c.setFont('Helvetica-Bold', size)
    c.drawCentredString(cx + w / 2, cy + h / 2 - 2, text[:28])


def build_timetable_pdf(run) -> bytes:
    ctx = school_sheet_context(run)
    bell = ctx['bell']
    buf = BytesIO()
    width, height = landscape(A3)
    c = canvas.Canvas(buf, pagesize=landscape(A3))
    margin = 8 * mm

    title = f"{bell.school_name} TIME - TABLE"
    c.setFont('Times-Bold', 16)
    c.drawCentredString(width / 2, height - 11 * mm, title)
    c.setFont('Times-Bold', 12)
    c.drawCentredString(width / 2, height - 17 * mm, bell.term_title)

    y_top = height - 20 * mm
    _draw_day_block(
        c,
        ctx,
        days=ctx['weekday_days'],
        slots=ctx['weekday_slots'],
        tables=ctx['weekday_tables'],
        extra_left=[
            (bell.assembly_time, 'ASSEMBLY'),
            (bell.attendance_time, 'ATTENDANCE'),
        ],
        extra_right=[],
        x=margin,
        y=y_top,
        max_width=width - 2 * margin,
        max_height=y_top - margin - 68 * mm,
    )
    friday_top = 76 * mm
    _draw_day_block(
        c,
        ctx,
        days=['Friday'],
        slots=ctx['friday_slots'],
        tables={'Friday': ctx['friday_rows']},
        extra_left=[],
        extra_right=[
            (bell.friday_club_time, bell.friday_club_label),
            (bell.friday_fellowship_time, bell.friday_fellowship_label),
        ],
        x=margin,
        y=friday_top,
        max_width=width - 2 * margin,
        max_height=friday_top - margin,
        day_abbrev={'Friday': 'Frid'},
    )
    c.save()
    return buf.getvalue()


def _draw_day_block(
    c,
    ctx,
    *,
    days,
    slots,
    tables,
    extra_left,
    extra_right,
    x,
    y,
    max_width,
    max_height,
    day_abbrev=None,
):
    classes = ctx['classes']
    n_class = max(len(classes), 1)
    n_days = len(days)
    abbrev = day_abbrev or ctx.get('day_abbrev') or {
        'Monday': 'Mon',
        'Tuesday': 'Tues',
        'Wednesday': 'Wed',
        'Thursday': 'Thur',
        'Friday': 'Frid',
    }
    day_w = 11 * mm
    class_w = 13 * mm
    extra_w = 8 * mm
    n_slot = len(slots)
    n_extra = len(extra_left) + len(extra_right)
    usable = max_width - day_w - class_w - extra_w * n_extra
    slot_w = usable / max(n_slot, 1)
    row_h = min(7.6 * mm, max_height / (1 + n_days * n_class))
    header_h = 12 * mm

    c.setStrokeColor(LINE)
    c.setLineWidth(0.35)
    hx = x
    hy = y - header_h
    c.setFillColor(HEAD_BG)
    c.rect(hx, hy, day_w + class_w, header_h, fill=1, stroke=1)

    col_x = hx + day_w + class_w
    for label_time, _label in extra_left:
        c.setFillColor(BREAK_BG)
        c.rect(col_x, hy, extra_w, header_h, fill=1, stroke=1)
        c.setFillColor(NAVY)
        c.setFont('Helvetica', 5)
        c.drawCentredString(col_x + extra_w / 2, hy + header_h - 7, label_time)
        col_x += extra_w
    for slot in slots:
        c.setFillColor(HEAD_BG)
        c.rect(col_x, hy, slot_w, header_h, fill=1, stroke=1)
        c.setFillColor(NAVY)
        c.setFont('Helvetica', 4.8)
        c.drawCentredString(col_x + slot_w / 2, hy + header_h - 7, _time_header(slot))
        if slot.period:
            c.setFont('Helvetica-Bold', 6)
            c.drawCentredString(col_x + slot_w / 2, hy + 3.5, f'P{slot.period}')
        col_x += slot_w
    for label_time, _label in extra_right:
        c.setFillColor(BREAK_BG)
        c.rect(col_x, hy, extra_w, header_h, fill=1, stroke=1)
        c.setFillColor(NAVY)
        c.setFont('Helvetica', 5)
        c.drawCentredString(col_x + extra_w / 2, hy + header_h - 7, label_time)
        col_x += extra_w

    body_h = row_h * n_days * n_class
    body_bottom = hy - body_h

    left_x = x + day_w + class_w
    for _label_time, label in extra_left:
        c.setFillColor(BREAK_BG)
        c.rect(left_x, body_bottom, extra_w, body_h, fill=1, stroke=1)
        _draw_vtext(c, label, left_x + extra_w / 2, body_bottom, body_h, size=8)
        left_x += extra_w

    right_start = left_x + slot_w * n_slot
    rx = right_start
    for _label_time, label in extra_right:
        c.setFillColor(BREAK_BG)
        c.rect(rx, body_bottom, extra_w, body_h, fill=1, stroke=1)
        _draw_vtext(c, label, rx + extra_w / 2, body_bottom, body_h, size=7)
        rx += extra_w

    break_drawn = set()
    cursor_y = hy
    for day in days:
        rows = tables[day]
        block_h = row_h * len(rows)
        day_bottom = cursor_y - block_h
        c.setFillColor(HEAD_BG)
        c.rect(x, day_bottom, day_w, block_h, fill=1, stroke=1)
        c.setFillColor(NAVY)
        c.setFont('Helvetica-Bold', 9)
        c.saveState()
        c.translate(x + day_w / 2, day_bottom + block_h / 2)
        c.rotate(90)
        c.drawCentredString(0, -3, abbrev.get(day, day[:3]))
        c.restoreState()

        for row in rows:
            ry = cursor_y - row_h
            c.setFillColor(colors.white)
            c.rect(x + day_w, ry, class_w, row_h, fill=1, stroke=1)
            c.setFillColor(NAVY)
            c.setFont('Helvetica-Bold', 6.5)
            label = getattr(row['class'], 'sheet_label', str(row['class']))
            c.drawCentredString(x + day_w + class_w / 2, ry + row_h / 2 - 2, label)
            cx = x + day_w + class_w + extra_w * len(extra_left)
            for cell, slot in zip(row['cells'], slots):
                kind = cell['kind']
                if kind == 'break':
                    if slot.sequence not in break_drawn:
                        c.setFillColor(BREAK_BG)
                        c.rect(cx, body_bottom, slot_w, body_h, fill=1, stroke=1)
                        _draw_vtext(
                            c,
                            cell.get('vlabel') or cell['text'],
                            cx + slot_w / 2,
                            body_bottom,
                            body_h,
                            size=8,
                        )
                        break_drawn.add(slot.sequence)
                else:
                    bg = SPORT_BG if kind == 'sport' else colors.white
                    c.setFillColor(bg)
                    c.rect(cx, ry, slot_w, row_h, fill=1, stroke=1)
                    _draw_cell_text(c, cell['text'], cx, ry, slot_w, row_h)
                cx += slot_w
            cursor_y = ry
