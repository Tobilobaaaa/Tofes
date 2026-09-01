"""Generate timetables and apply clash-checked manual adjustments."""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db import transaction

from .genetic_algorithm import SchoolTimetableGA, build_sessions
from .models import (
    BellSettings,
    ClassAssignment,
    DayOfWeek,
    SchoolClass,
    SlotKind,
    TeacherAvailability,
    TimeSlot,
    TimetableEntry,
    TimetableRun,
)

FRENCH_SUBJECT_CODE = 'FRE'


def _add_minutes(clock, minutes):
    base = datetime.combine(datetime.today(), clock)
    return (base + timedelta(minutes=minutes)).time()


def french_monday_period_range(
    bell: BellSettings | None = None,
    class_count: int | None = None,
) -> tuple[int, int]:
    """Consecutive Monday periods for French, starting right after the long break."""
    bell = bell or BellSettings.load()
    start = bell.first_period_after_long_break
    if class_count is None:
        class_count = ClassAssignment.objects.filter(
            subject__code=FRENCH_SUBJECT_CODE
        ).count()
    class_count = max(1, class_count)
    return start, start + class_count - 1


def french_slot_rule_violation(
    subject_code: str,
    day: str,
    period: int,
    bell: BellSettings | None = None,
    class_count: int | None = None,
) -> str | None:
    """Return a message when French is outside its fixed Monday block."""
    if subject_code != FRENCH_SUBJECT_CODE:
        return None
    bell = bell or BellSettings.load()
    start, end = french_monday_period_range(bell, class_count)
    if day != DayOfWeek.MONDAY:
        return 'French must be scheduled on Monday only.'
    if period < start or period > end:
        if start == end:
            return (
                f'French must be in period {start} '
                f'(immediately after the long break).'
            )
        return (
            f'French must be on Monday in period(s) {start}–{end} '
            f'(starting immediately after the long break).'
        )
    return None


def subject_allowed_slot_indices(
    timeslots: list[dict],
    bell: BellSettings | None = None,
    class_count: int | None = None,
) -> dict[str, set[int]]:
    """Hard placement rules keyed by subject code."""
    bell = bell or BellSettings.load()
    start, end = french_monday_period_range(bell, class_count)
    french_slots = {
        i
        for i, ts in enumerate(timeslots)
        if ts['day'] == DayOfWeek.MONDAY
        and start <= ts['period'] <= end
        and not ts.get('is_break')
        and not ts.get('is_reserved')
    }
    if not french_slots:
        return {}
    return {FRENCH_SUBJECT_CODE: french_slots}


def rebuild_time_slots(settings: BellSettings | None = None) -> int:
    """Rebuild Mon–Fri slots from bell settings. Replaces existing periods."""
    settings = settings or BellSettings.load()
    TimeSlot.objects.all().delete()

    weekday_limit = settings.weekday_periods
    created = 0

    blocks = [
        (SlotKind.TEACHING, settings.periods_before_short_break, settings.period_minutes),
        (SlotKind.SHORT_BREAK, 1, settings.short_break_minutes),
        (SlotKind.TEACHING, settings.periods_before_long_break, settings.period_minutes),
        (SlotKind.LONG_BREAK, 1, settings.long_break_minutes),
        (SlotKind.TEACHING, settings.periods_before_lesson_break, settings.period_minutes),
        (SlotKind.LESSON_BREAK, 1, settings.lesson_break_minutes),
        (SlotKind.TEACHING, settings.periods_after_lesson_break, settings.period_minutes),
    ]

    for day, _ in DayOfWeek.choices:
        teach_limit = settings.friday_periods if day == DayOfWeek.FRIDAY else weekday_limit
        cursor = settings.start_time
        sequence = 1
        teaching_no = 0
        for kind, count, duration in blocks:
            if kind != SlotKind.TEACHING:
                if teaching_no >= teach_limit:
                    break
                start = cursor
                end = _add_minutes(cursor, duration)
                TimeSlot.objects.create(
                    day=day,
                    sequence=sequence,
                    period=0,
                    start_time=start,
                    end_time=end,
                    kind=kind,
                    is_break=True,
                    is_reserved=False,
                    label='',
                )
                cursor = end
                sequence += 1
                created += 1
                continue
            for _n in range(count):
                if teaching_no >= teach_limit:
                    break
                teaching_no += 1
                start = cursor
                end = _add_minutes(cursor, duration)
                reserved = (
                    day == DayOfWeek.WEDNESDAY
                    and teaching_no == 1
                    and settings.wednesday_p1_is_sport
                )
                TimeSlot.objects.create(
                    day=day,
                    sequence=sequence,
                    period=teaching_no,
                    start_time=start,
                    end_time=end,
                    kind=SlotKind.RESERVED if reserved else SlotKind.TEACHING,
                    is_break=False,
                    is_reserved=reserved,
                    activity_name=settings.wednesday_activity if reserved else '',
                    label='',
                )
                cursor = end
                sequence += 1
                created += 1
    return created


def refresh_group_period_hint(group):
    """Store the busiest member's load on the group; do not overwrite subjects."""
    loads = list(group.subjects.values_list('default_periods', flat=True))
    if not loads:
        return
    hint = max(loads)
    if group.periods_per_week != hint:
        group.periods_per_week = hint
        group.save(update_fields=['periods_per_week'])


def sync_group_assignments(group):
    """Keep the group linked; subjects keep their own periods/week."""
    refresh_group_period_hint(group)


def apply_subject_periods(subject, periods: int) -> int:
    """Set weekly periods for one subject (and every class that takes it)."""
    periods = max(1, int(periods))
    subject.default_periods = periods
    subject.save(update_fields=['default_periods'])
    updated = ClassAssignment.objects.filter(subject=subject).update(
        periods_per_week=periods
    )
    if subject.simultaneous_group_id:
        refresh_group_period_hint(subject.simultaneous_group)
    return updated


def teacher_load_issues() -> list[dict]:
    """Teachers whose weekly lessons exceed available teaching slots."""
    capacity = TimeSlot.objects.filter(is_break=False, is_reserved=False).count()
    issues = []
    from .models import Teacher

    for teacher in Teacher.objects.prefetch_related('assignments'):
        load = sum(
            a.periods_per_week for a in teacher.assignments.all()
        )
        if load > capacity:
            issues.append(
                {
                    'teacher': teacher,
                    'load': load,
                    'capacity': capacity,
                    'over': load - capacity,
                }
            )
    return issues


def _slot_maps():
    slots = list(TimeSlot.objects.all())
    timeslots = [
        {
            'id': s.id,
            'day': s.day,
            'period': s.period,
            'sequence': s.sequence,
            'label': s.label,
            'is_break': s.is_break,
            'is_reserved': s.is_reserved,
            'activity_name': s.activity_name,
        }
        for s in slots
    ]
    id_to_idx = {s['id']: i for i, s in enumerate(timeslots)}
    return slots, timeslots, id_to_idx


def _availability_maps(slot_id_to_idx):
    preferred: dict[int, set[int]] = {}
    unavailable: dict[int, set[int]] = {}
    for pref in TeacherAvailability.objects.select_related('time_slot'):
        idx = slot_id_to_idx.get(pref.time_slot_id)
        if idx is None:
            continue
        if pref.is_preferred:
            preferred.setdefault(pref.teacher_id, set()).add(idx)
        else:
            unavailable.setdefault(pref.teacher_id, set()).add(idx)
    return preferred, unavailable


def _locked_from_active_run(slot_id_to_idx):
    active = TimetableRun.objects.filter(is_active=True).first()
    if not active:
        return {}
    locked = {}
    qs = active.entries.filter(is_locked=True).select_related('time_slot')
    for entry in qs:
        idx = slot_id_to_idx.get(entry.time_slot_id)
        if idx is None:
            continue
        key = (entry.school_class_id, entry.subject_id, entry.session_index)
        locked[key] = idx
    return locked


def generate_timetable(
    *,
    name: str = '',
    population_size: int = 36,
    max_generations: int = 40,
    crossover_prob: float = 0.7,
    mutation_prob: float = 0.25,
    publish: bool = True,
    keep_locked: bool = False,
) -> TimetableRun:
    run = TimetableRun.objects.create(
        name=name or '',
        status=TimetableRun.Status.RUNNING,
        population_size=population_size,
        max_generations=max_generations,
        crossover_prob=crossover_prob,
        mutation_prob=mutation_prob,
        keep_locked=keep_locked,
    )
    if not run.name:
        run.name = f'Timetable #{run.pk}'
        run.save(update_fields=['name'])

    try:
        assignments = list(
            ClassAssignment.objects.select_related(
                'school_class', 'subject', 'subject__simultaneous_group', 'teacher'
            )
        )
        _slots, timeslots, slot_id_to_idx = _slot_maps()
        preferred, unavailable = _availability_maps(slot_id_to_idx)
        locked = _locked_from_active_run(slot_id_to_idx) if keep_locked else {}
        bell = BellSettings.load()
        class_ids = list(SchoolClass.objects.values_list('id', flat=True))

        sessions = build_sessions(assignments, locked_by_key=locked)
        subject_slots = subject_allowed_slot_indices(timeslots, bell)
        ga = SchoolTimetableGA(
            sessions=sessions,
            timeslots=timeslots,
            preferred_slots=preferred,
            unavailable_slots=unavailable,
            class_ids=class_ids,
            min_periods_weekday=bell.min_periods_weekday,
            friday_periods=bell.friday_periods,
            subject_allowed_slots=subject_slots,
            population_size=population_size,
            max_generations=max_generations,
            crossover_prob=crossover_prob,
            mutation_prob=mutation_prob,
        )
        result = ga.run()

        with transaction.atomic():
            entries = []
            for i, slot_idx in enumerate(result.best_chromosome):
                session = sessions[i]
                slot_id = timeslots[slot_idx]['id']
                locked_here = session.locked_slot_idx is not None
                for part in session.parts:
                    entries.append(
                        TimetableEntry(
                            run=run,
                            school_class_id=part.class_id,
                            subject_id=part.subject_id,
                            teacher_id=part.teacher_id,
                            time_slot_id=slot_id,
                            session_index=session.session_index,
                            option_group=part.option_group,
                            is_locked=locked_here,
                            is_manual=False,
                        )
                    )
            TimetableEntry.objects.bulk_create(entries)

            hard, soft, details = count_run_violations(run)
            run.status = TimetableRun.Status.COMPLETED
            run.generations_run = result.generations
            run.best_fitness = result.best_fitness
            run.hard_violations = hard
            run.soft_violations = soft
            run.execution_seconds = result.execution_seconds
            run.fitness_history = result.fitness_history
            extra = f' {len(details)} clash notes.' if details and hard else ''
            overload = teacher_load_issues()
            if overload:
                bits = ', '.join(
                    f"{item['teacher'].name} {item['load']}/{item['capacity']}"
                    for item in overload
                )
                extra += (
                    f' Cannot be clash-free until teacher load fits the week: {bits}.'
                )
            run.message = result.message + extra
            run.is_active = publish and hard == 0
            run.save()

        return run

    except Exception as exc:  # noqa: BLE001
        run.status = TimetableRun.Status.FAILED
        run.message = str(exc)
        run.save(update_fields=['status', 'message', 'updated_at'])
        raise


def count_run_violations(run: TimetableRun) -> tuple[int, int, list[str]]:
    """Re-score a saved timetable after generation or manual edits."""
    entries = list(
        run.entries.select_related('school_class', 'subject', 'teacher', 'time_slot')
    )
    hard = 0
    soft = 0
    details: list[str] = []

    teacher_at: dict[tuple[int, int], list[TimetableEntry]] = {}
    class_at: dict[tuple[int, int], list[TimetableEntry]] = {}
    class_day_subject_periods: dict[tuple[int, str, int], list[int]] = {}

    unavailable = {
        (p.teacher_id, p.time_slot_id)
        for p in TeacherAvailability.objects.filter(is_preferred=False)
    }
    bell = BellSettings.load()

    for entry in entries:
        slot = entry.time_slot
        if slot.is_break:
            hard += 1
            details.append(
                f'{entry.school_class} {entry.subject.code} is on a break ({slot}).'
            )
        if slot.is_reserved:
            hard += 1
            details.append(
                f'{entry.school_class} {entry.subject.code} is on reserved {slot.activity_name or "slot"} ({slot}).'
            )

        tk = (entry.teacher_id, slot.id)
        teacher_at.setdefault(tk, []).append(entry)
        ck = (entry.school_class_id, slot.id)
        class_at.setdefault(ck, []).append(entry)

        if (entry.teacher_id, slot.id) in unavailable:
            hard += 1
            details.append(
                f'{entry.teacher.name} is marked unavailable at {slot} '
                f'({entry.school_class} {entry.subject.code}).'
            )

        rule = french_slot_rule_violation(
            entry.subject.code, slot.day, slot.period, bell
        )
        if rule:
            hard += 1
            details.append(
                f'{entry.school_class} {entry.subject.code} at {slot}: {rule}'
            )

        key = (entry.school_class_id, slot.day, entry.subject_id)
        class_day_subject_periods.setdefault(key, []).append(slot.period)

    for (_teacher_id, _slot_id), group in teacher_at.items():
        if len(group) > 1:
            hard += len(group) - 1
            names = ', '.join(
                f'{e.school_class} {e.subject.code}' for e in group
            )
            details.append(
                f'{group[0].teacher.name} is double-booked at {group[0].time_slot}: {names}.'
            )

    for (_class_id, _slot_id), group in class_at.items():
        option_groups = {e.option_group for e in group if e.option_group}
        if len(group) <= 1:
            continue
        if len(option_groups) == 1 and all(e.option_group for e in group):
            continue
        hard += len(group) - 1
        names = ', '.join(e.subject.code for e in group)
        details.append(
            f'{group[0].school_class} has overlapping lessons at {group[0].time_slot}: {names}.'
        )

    for periods in class_day_subject_periods.values():
        if len(periods) < 2:
            continue
        ordered = sorted(periods)
        consecutive = any(
            ordered[i + 1] - ordered[i] == 1 for i in range(len(ordered) - 1)
        )
        if not consecutive:
            soft += len(ordered) - 1

    return hard, soft, details


def refresh_run_score(run: TimetableRun) -> TimetableRun:
    hard, soft, details = count_run_violations(run)
    run.hard_violations = hard
    run.soft_violations = soft
    if hard == 0:
        run.message = 'Clash-free timetable.' + (
            f' {soft} soft preference issue(s).' if soft else ''
        )
    else:
        preview = ' '.join(details[:4])
        run.message = f'{hard} hard clash(es). {preview}'
    run.save(update_fields=['hard_violations', 'soft_violations', 'message', 'updated_at'])
    return run


def _bundle_entries(entry: TimetableEntry, move_group: bool) -> list[TimetableEntry]:
    if not move_group or not entry.option_group:
        return [entry]
    return list(
        TimetableEntry.objects.filter(
            run=entry.run,
            school_class=entry.school_class,
            option_group=entry.option_group,
            time_slot=entry.time_slot,
            session_index=entry.session_index,
        )
    )


def clash_reasons_for_move(
    entries: list[TimetableEntry],
    new_slot: TimeSlot,
    extra_leaving: list[TimetableEntry] | None = None,
) -> list[str]:
    """Would these entries clash if placed on new_slot?"""
    extra_leaving = extra_leaving or []
    ignore_ids = {e.id for e in entries} | {e.id for e in extra_leaving}
    reasons: list[str] = []
    if new_slot.is_break:
        reasons.append(f'{new_slot} is a break, not a teaching period.')
        return reasons
    if new_slot.is_reserved:
        reasons.append(
            f'{new_slot} is reserved for {new_slot.activity_name or "a school activity"}.'
        )
        return reasons

    run = entries[0].run
    others = list(
        TimetableEntry.objects.filter(run=run, time_slot=new_slot)
        .exclude(pk__in=ignore_ids)
        .select_related('school_class', 'subject', 'teacher', 'time_slot')
    )

    unavailable = set(
        TeacherAvailability.objects.filter(
            is_preferred=False, time_slot=new_slot
        ).values_list('teacher_id', flat=True)
    )

    for entry in entries:
        if entry.teacher_id in unavailable:
            reasons.append(
                f'{entry.teacher.name} is marked unavailable at {new_slot}.'
            )
        rule = french_slot_rule_violation(
            entry.subject.code, new_slot.day, new_slot.period
        )
        if rule:
            reasons.append(f'{entry.subject.code}: {rule}')
        for other in others:
            if other.teacher_id == entry.teacher_id:
                reasons.append(
                    f'{entry.teacher.name} already teaches {other.school_class} '
                    f'{other.subject.code} at {new_slot}.'
                )
            if other.school_class_id == entry.school_class_id:
                same_group = (
                    entry.option_group
                    and other.option_group
                    and entry.option_group == other.option_group
                )
                if not same_group:
                    reasons.append(
                        f'{entry.school_class} already has {other.subject.code} at {new_slot}.'
                    )
    # Unique while preserving order
    seen = set()
    unique = []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            unique.append(reason)
    return unique


def move_entry(
    entry: TimetableEntry,
    new_slot: TimeSlot,
    *,
    force: bool = False,
    move_group: bool = True,
) -> tuple[bool, list[str]]:
    entries = _bundle_entries(entry, move_group)
    reasons = clash_reasons_for_move(entries, new_slot)
    if reasons and not force:
        return False, reasons

    with transaction.atomic():
        for item in entries:
            item.time_slot = new_slot
            item.is_manual = True
            item.save(update_fields=['time_slot', 'is_manual'])
        refresh_run_score(entry.run)
    return True, reasons


def swap_entries(
    entry_a: TimetableEntry,
    entry_b: TimetableEntry,
    *,
    force: bool = False,
    move_group: bool = True,
) -> tuple[bool, list[str]]:
    if entry_a.run_id != entry_b.run_id:
        return False, ['Lessons must belong to the same timetable.']
    if entry_a.id == entry_b.id:
        return False, ['Choose two different lessons to swap.']

    group_a = _bundle_entries(entry_a, move_group)
    group_b = _bundle_entries(entry_b, move_group)
    ids_a = {e.id for e in group_a}
    ids_b = {e.id for e in group_b}
    if ids_a & ids_b:
        return False, ['Those lessons are already in the same elective block.']

    slot_a = entry_a.time_slot
    slot_b = entry_b.time_slot
    reasons = clash_reasons_for_move(group_a, slot_b, extra_leaving=group_b)
    reasons += clash_reasons_for_move(group_b, slot_a, extra_leaving=group_a)
    if reasons and not force:
        return False, reasons

    with transaction.atomic():
        for item in group_a:
            item.time_slot = slot_b
            item.is_manual = True
            item.save(update_fields=['time_slot', 'is_manual'])
        for item in group_b:
            item.time_slot = slot_a
            item.is_manual = True
            item.save(update_fields=['time_slot', 'is_manual'])
        refresh_run_score(entry_a.run)
    return True, reasons


def set_entry_lock(entry: TimetableEntry, locked: bool, move_group: bool = True):
    entries = _bundle_entries(entry, move_group)
    TimetableEntry.objects.filter(pk__in=[e.id for e in entries]).update(is_locked=locked)
    return entries


def load_run_with_entries(run: TimetableRun):
    return run.entries.select_related(
        'school_class', 'subject', 'teacher', 'time_slot'
    )


def lesson_cell_text(entries) -> str:
    """Subject codes exactly as shown on the generated class grid."""
    if not entries:
        return ''
    codes = []
    seen = set()
    for entry in sorted(entries, key=lambda e: e.subject.code):
        code = entry.subject.code
        if code not in seen:
            seen.add(code)
            codes.append(code)
    return '/'.join(codes)


_BREAK_VLABEL = {
    'short_break': 'SHORT',
    'long_break': 'LONG',
    'lesson_break': 'LESSON',
}

_DAY_ABBREV = {
    'Monday': 'Mon',
    'Tuesday': 'Tues',
    'Wednesday': 'Wed',
    'Thursday': 'Thur',
    'Friday': 'Frid',
}


def school_sheet_context(run: TimetableRun) -> dict:
    """Data for the college-style print/PDF sheet."""
    from .models import BellSettings, DayOfWeek, SchoolClass

    bell = BellSettings.load()
    classes = sorted(SchoolClass.objects.all(), key=lambda c: c.sort_key)
    days = [d[0] for d in DayOfWeek.choices]
    weekday_slots = list(TimeSlot.objects.filter(day='Monday'))
    friday_slots = list(TimeSlot.objects.filter(day='Friday'))
    slots_by_day: dict[str, dict[int, TimeSlot]] = {}
    for slot in TimeSlot.objects.all():
        slots_by_day.setdefault(slot.day, {})[slot.sequence] = slot
    entries = list(
        run.entries.select_related('school_class', 'subject', 'teacher', 'time_slot')
    )
    by_key: dict[tuple[int, int], list] = {}
    for entry in entries:
        by_key.setdefault((entry.school_class_id, entry.time_slot_id), []).append(entry)

    def rows_for(day, slots):
        rows = []
        for school_class in classes:
            cells = []
            for template in slots:
                slot = slots_by_day.get(day, {}).get(template.sequence, template)
                if slot.is_break:
                    cells.append(
                        {
                            'kind': 'break',
                            'text': slot.get_kind_display().upper(),
                            'vlabel': _BREAK_VLABEL.get(
                                slot.kind, slot.get_kind_display().upper()
                            ),
                        }
                    )
                elif slot.is_reserved:
                    cells.append(
                        {
                            'kind': 'sport',
                            'text': (slot.activity_name or 'SPORT').upper(),
                            'vlabel': '',
                        }
                    )
                else:
                    items = by_key.get((school_class.id, slot.id), [])
                    cells.append(
                        {
                            'kind': 'lesson',
                            'text': lesson_cell_text(items),
                            'vlabel': '',
                        }
                    )
            rows.append({'class': school_class, 'cells': cells})
        return rows

    weekday_days = [d for d in days if d != 'Friday']
    weekday_blocks = [
        {
            'day': day,
            'abbrev': _DAY_ABBREV.get(day, day[:3]),
            'rows': rows_for(day, weekday_slots),
        }
        for day in weekday_days
    ]
    return {
        'run': run,
        'bell': bell,
        'classes': classes,
        'day_abbrev': _DAY_ABBREV,
        'weekday_days': weekday_days,
        'weekday_slots': weekday_slots,
        'friday_slots': friday_slots,
        'weekday_tables': {block['day']: block['rows'] for block in weekday_blocks},
        'weekday_blocks': weekday_blocks,
        'weekday_rowspan': max(len(weekday_days) * len(classes), 1),
        'friday_rows': rows_for('Friday', friday_slots),
        'friday_rowspan': max(len(classes), 1),
    }
