from django.db import IntegrityError
from django.db.models import Count, ProtectedError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.views.decorators.http import require_POST
from openpyxl import Workbook

from .models import (
    BellSettings,
    ClassAssignment,
    ClassLevel,
    DayOfWeek,
    SchoolClass,
    Section,
    SimultaneousGroup,
    Subject,
    Teacher,
    TeacherAvailability,
    TeacherSubject,
    TimeSlot,
    TimetableEntry,
    TimetableRun,
)
from .services import (
    apply_subject_periods,
    count_run_violations,
    generate_timetable,
    move_entry,
    rebuild_time_slots,
    refresh_group_period_hint,
    refresh_run_score,
    school_sheet_context,
    set_entry_lock,
    swap_entries,
    teacher_load_issues,
)


def _safe_delete(request, model, pk, redirect_name, label='Item'):
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        messages.info(request, f'{label} was already removed or does not exist.')
        return redirect(redirect_name)
    try:
        obj.delete()
    except ProtectedError:
        messages.error(
            request,
            f'Cannot delete this {label.lower()}: it is still used on class assignments.',
        )
        return redirect(redirect_name)
    messages.success(request, f'{label} deleted.')
    return redirect(redirect_name)


def dashboard(request):
    active = TimetableRun.objects.filter(is_active=True).first()
    teachers = Teacher.objects.annotate(n_subjects=Count('can_teach'))
    heavy = [t for t in teachers if t.n_subjects > 4]
    context = {
        'stats': {
            'teachers': Teacher.objects.count(),
            'subjects': Subject.objects.count(),
            'classes': SchoolClass.objects.count(),
            'assignments': ClassAssignment.objects.count(),
            'slots': TimeSlot.objects.filter(is_break=False).count(),
            'runs': TimetableRun.objects.count(),
        },
        'active_run': active,
        'recent_runs': TimetableRun.objects.all()[:5],
        'heavy_teachers': heavy,
    }
    return render(request, 'timetable/dashboard.html', context)


def teachers_page(request):
    if request.method == 'POST':
        teacher = Teacher.objects.create(
            name=request.POST.get('name', '').strip(),
            email=request.POST.get('email', '').strip(),
            phone=request.POST.get('phone', '').strip(),
            notes=request.POST.get('notes', '').strip(),
        )
        subject_ids = request.POST.getlist('subjects')
        fallback_scope = request.POST.get('section_scope', Section.BOTH)
        for sid in subject_ids:
            subject = Subject.objects.filter(pk=int(sid)).first()
            if not subject:
                continue
            scope = subject.section if subject.section != Section.BOTH else fallback_scope
            TeacherSubject.objects.get_or_create(
                teacher=teacher,
                subject=subject,
                defaults={'section_scope': scope},
            )
        n = len(subject_ids)
        if n > 4:
            messages.warning(
                request,
                f'{teacher.name} saved with {n} subjects. Aim for 3–4 so the timetable stays feasible.',
            )
        else:
            messages.success(request, f'{teacher.name} added.')
        return redirect('teachers')

    teachers = Teacher.objects.prefetch_related('can_teach__subject').annotate(
        n_subjects=Count('can_teach')
    )
    return render(
        request,
        'timetable/teachers.html',
        {
            'teachers': teachers,
            'subjects': Subject.objects.all(),
            'sections': Section.choices,
        },
    )


def edit_teacher(request, pk):
    teacher = Teacher.objects.filter(pk=pk).first()
    if teacher is None:
        messages.info(request, 'Teacher was already removed.')
        return redirect('teachers')
    if request.method == 'POST':
        teacher.name = request.POST.get('name', '').strip()
        teacher.email = request.POST.get('email', '').strip()
        teacher.phone = request.POST.get('phone', '').strip()
        teacher.notes = request.POST.get('notes', '').strip()
        teacher.save()
        TeacherSubject.objects.filter(teacher=teacher).delete()
        fallback_scope = request.POST.get('section_scope', Section.BOTH)
        for sid in request.POST.getlist('subjects'):
            subject = Subject.objects.filter(pk=int(sid)).first()
            if not subject:
                continue
            scope = subject.section if subject.section != Section.BOTH else fallback_scope
            TeacherSubject.objects.create(
                teacher=teacher,
                subject=subject,
                section_scope=scope,
            )
        messages.success(request, f'{teacher.name} updated.')
        return redirect('teachers')

    selected = set(teacher.can_teach.values_list('subject_id', flat=True))
    return render(
        request,
        'timetable/teachers.html',
        {
            'teachers': Teacher.objects.prefetch_related('can_teach__subject').annotate(
                n_subjects=Count('can_teach')
            ),
            'subjects': Subject.objects.all(),
            'sections': Section.choices,
            'editing': teacher,
            'selected_subject_ids': selected,
        },
    )


def delete_teacher(request, pk):
    return _safe_delete(request, Teacher, pk, 'teachers', 'Teacher')


def subjects_page(request):
    if request.method == 'POST':
        code = request.POST.get('code', '').strip().upper()
        if not code or not request.POST.get('name', '').strip():
            messages.error(request, 'Code and name are required.')
            return redirect('subjects')
        group_id = request.POST.get('simultaneous_group') or None
        if Subject.objects.filter(code=code).exists():
            messages.error(request, f'Subject code "{code}" is already used.')
            return redirect('subjects')
        group = SimultaneousGroup.objects.filter(pk=group_id).first() if group_id else None
        periods = int(request.POST.get('default_periods', 2) or 2)
        if group:
            periods = group.periods_per_week
        Subject.objects.create(
            name=request.POST.get('name', '').strip(),
            code=code,
            section=request.POST.get('section', Section.JUNIOR),
            simultaneous_group=group,
            default_periods=periods,
        )
        if group:
            refresh_group_period_hint(group)
        messages.success(request, f'Subject {code} added.')
        return redirect('subjects')
    return render(
        request,
        'timetable/subjects.html',
        {
            'subjects': Subject.objects.select_related('simultaneous_group'),
            'sections': Section.choices,
            'groups': SimultaneousGroup.objects.all(),
        },
    )


def edit_subject(request, pk):
    subject = Subject.objects.filter(pk=pk).first()
    if subject is None:
        messages.info(request, 'Subject was already removed.')
        return redirect('subjects')
    if request.method == 'POST':
        code = request.POST.get('code', '').strip().upper()
        clash = Subject.objects.filter(code=code).exclude(pk=subject.pk)
        if clash.exists():
            messages.error(request, f'Subject code "{code}" is already used.')
            return redirect('edit_subject', pk=pk)
        group_id = request.POST.get('simultaneous_group') or None
        group = SimultaneousGroup.objects.filter(pk=group_id).first() if group_id else None
        subject.name = request.POST.get('name', '').strip()
        subject.code = code
        subject.section = request.POST.get('section', subject.section)
        subject.simultaneous_group = group
        periods = int(request.POST.get('default_periods', 2) or 2)
        subject.save()
        apply_subject_periods(subject, periods)
        if group:
            refresh_group_period_hint(group)
        messages.success(request, f'{subject.code} updated.')
        return redirect('subjects')
    return render(
        request,
        'timetable/subjects.html',
        {
            'subjects': Subject.objects.select_related('simultaneous_group'),
            'sections': Section.choices,
            'groups': SimultaneousGroup.objects.all(),
            'editing': subject,
        },
    )


def delete_subject(request, pk):
    return _safe_delete(request, Subject, pk, 'subjects', 'Subject')


@require_POST
def update_subject_periods(request, pk):
    subject = Subject.objects.filter(pk=pk).select_related('simultaneous_group').first()
    if subject is None:
        messages.info(request, 'Subject was already removed.')
        return redirect('subjects')
    periods = int(request.POST.get('periods_per_week', subject.default_periods) or 1)
    n = apply_subject_periods(subject, periods)
    extra = ''
    if subject.simultaneous_group_id:
        extra = (
            f' Other subjects in “{subject.simultaneous_group.name}” keep their own '
            f'periods/week (a stream can be free on extra slots).'
        )
    messages.success(
        request,
        f'{subject.code} now has {periods} period(s) per week'
        f'{f" on {n} class assignment(s)" if n else ""}.{extra}',
    )
    return redirect('subjects')


def simultaneous_page(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'Give the simultaneous block a name.')
            return redirect('simultaneous')
        group = SimultaneousGroup.objects.create(
            name=name,
            section=request.POST.get('section', Section.SENIOR),
            periods_per_week=int(request.POST.get('periods_per_week', 3) or 3),
        )
        subject_ids = [int(x) for x in request.POST.getlist('subjects') if str(x).isdigit()]
        Subject.objects.filter(pk__in=subject_ids).update(simultaneous_group=group)
        refresh_group_period_hint(group)
        messages.success(
            request,
            f'{group.name} saved. Those subjects share a period when they both have a lesson that week.',
        )
        return redirect('simultaneous')

    return render(
        request,
        'timetable/simultaneous.html',
        {
            'groups': SimultaneousGroup.objects.prefetch_related('subjects'),
            'subjects': Subject.objects.filter(section=Section.SENIOR),
            'sections': Section.choices,
        },
    )


def edit_simultaneous(request, pk):
    group = SimultaneousGroup.objects.filter(pk=pk).prefetch_related('subjects').first()
    if group is None:
        messages.info(request, 'That block was already removed.')
        return redirect('simultaneous')
    if request.method == 'POST':
        group.name = request.POST.get('name', '').strip() or group.name
        group.section = request.POST.get('section', group.section)
        group.periods_per_week = int(
            request.POST.get('periods_per_week', group.periods_per_week) or 3
        )
        group.save()
        Subject.objects.filter(simultaneous_group=group).update(simultaneous_group=None)
        subject_ids = [int(x) for x in request.POST.getlist('subjects') if str(x).isdigit()]
        Subject.objects.filter(pk__in=subject_ids).update(simultaneous_group=group)
        refresh_group_period_hint(group)
        messages.success(request, f'{group.name} updated. Each subject keeps its own periods/week.')
        return redirect('simultaneous')
    selected = set(group.subjects.values_list('id', flat=True))
    return render(
        request,
        'timetable/simultaneous.html',
        {
            'groups': SimultaneousGroup.objects.prefetch_related('subjects'),
            'subjects': Subject.objects.filter(section=Section.SENIOR),
            'sections': Section.choices,
            'editing': group,
            'selected_ids': selected,
        },
    )


def delete_simultaneous(request, pk):
    group = SimultaneousGroup.objects.filter(pk=pk).first()
    if group:
        Subject.objects.filter(simultaneous_group=group).update(simultaneous_group=None)
        group.delete()
        messages.success(request, 'Simultaneous block removed. Subjects are now standalone.')
    return redirect('simultaneous')


def classes_page(request):
    if request.method == 'POST':
        try:
            SchoolClass.objects.create(
                level=request.POST.get('level'),
                arm=request.POST.get('arm', '').strip().upper(),
            )
            messages.success(request, 'Class added.')
        except IntegrityError:
            messages.error(request, 'That class / arm already exists.')
        return redirect('classes')
    classes = sorted(SchoolClass.objects.all(), key=lambda c: c.sort_key)
    return render(
        request,
        'timetable/classes.html',
        {'classes': classes, 'levels': ClassLevel.choices},
    )


def delete_class(request, pk):
    return _safe_delete(request, SchoolClass, pk, 'classes', 'Class')


def _eligible_teachers(subject, school_class):
    links = TeacherSubject.objects.filter(subject=subject).select_related('teacher')
    teachers = []
    seen = set()
    for link in links:
        if link.covers_class(school_class) and link.teacher_id not in seen:
            teachers.append(link.teacher)
            seen.add(link.teacher_id)
    return teachers


def assignments_page(request):
    if request.method == 'POST':
        class_id = int(request.POST.get('school_class'))
        subject_id = int(request.POST.get('subject'))
        teacher_id = int(request.POST.get('teacher'))
        periods = int(request.POST.get('periods_per_week', 2) or 2)
        school_class = get_object_or_404(SchoolClass, pk=class_id)
        subject = get_object_or_404(Subject, pk=subject_id)
        if subject.section != Section.BOTH and subject.section != school_class.section:
            messages.error(
                request,
                f'{subject.name} is a {subject.get_section_display()} subject and does not match {school_class}.',
            )
            return redirect('assignments')
        try:
            ClassAssignment.objects.update_or_create(
                school_class_id=class_id,
                subject_id=subject_id,
                defaults={'teacher_id': teacher_id, 'periods_per_week': periods},
            )
            messages.success(request, 'Class assignment saved.')
        except IntegrityError:
            messages.error(request, 'Could not save that assignment.')
        return redirect('assignments')

    assignments = ClassAssignment.objects.select_related(
        'school_class', 'subject', 'teacher'
    )
    return render(
        request,
        'timetable/assignments.html',
        {
            'assignments': assignments,
            'classes': sorted(SchoolClass.objects.all(), key=lambda c: c.sort_key),
            'subjects': Subject.objects.select_related('simultaneous_group'),
            'teachers': Teacher.objects.all(),
        },
    )


def delete_assignment(request, pk):
    return _safe_delete(request, ClassAssignment, pk, 'assignments', 'Assignment')


@require_POST
def update_assignment_periods(request, pk):
    assignment = ClassAssignment.objects.filter(pk=pk).select_related(
        'subject', 'school_class', 'subject__simultaneous_group'
    ).first()
    if assignment is None:
        messages.info(request, 'Assignment was already removed.')
        return redirect('assignments')
    periods = max(1, int(request.POST.get('periods_per_week', 1) or 1))
    assignment.periods_per_week = periods
    assignment.save(update_fields=['periods_per_week'])
    extra = ''
    if assignment.subject.simultaneous_group_id:
        extra = ' Other streams in the same block keep their own weekly count.'
    messages.success(
        request,
        f'{assignment.school_class} {assignment.subject.code}: {periods} period(s) per week.{extra}',
    )
    return redirect('assignments')


def slots_page(request):
    bell = BellSettings.load()
    if request.method == 'POST':
        action = request.POST.get('action', 'rebuild')
        if action == 'update_slot':
            slot = TimeSlot.objects.filter(pk=request.POST.get('slot_id')).first()
            if slot:
                from datetime import time as dtime

                start = request.POST.get('start_time', '08:30')
                end = request.POST.get('end_time', '09:10')
                sh, sm = map(int, start.split(':'))
                eh, em = map(int, end.split(':'))
                slot.start_time = dtime(sh, sm)
                slot.end_time = dtime(eh, em)
                slot.label = ''
                slot.save()
                messages.success(request, f'{slot.day} updated.')
            return redirect('slots')

        bell.school_name = (
            request.POST.get('school_name', '').strip() or bell.school_name
        )
        bell.term_title = request.POST.get('term_title', '').strip() or bell.term_title
        bell.assembly_time = (
            request.POST.get('assembly_time', '').strip() or bell.assembly_time
        )
        bell.attendance_time = (
            request.POST.get('attendance_time', '').strip() or bell.attendance_time
        )
        bell.friday_club_time = (
            request.POST.get('friday_club_time', '').strip() or bell.friday_club_time
        )
        bell.friday_club_label = (
            request.POST.get('friday_club_label', '').strip() or bell.friday_club_label
        )
        bell.friday_fellowship_time = (
            request.POST.get('friday_fellowship_time', '').strip()
            or bell.friday_fellowship_time
        )
        bell.friday_fellowship_label = (
            request.POST.get('friday_fellowship_label', '').strip()
            or bell.friday_fellowship_label
        )
        if action == 'save_header':
            bell.save()
            messages.success(request, 'School name, term and print columns saved.')
            return redirect('slots')

        bell.start_time = request.POST.get('start_time') or bell.start_time
        bell.period_minutes = int(request.POST.get('period_minutes', 40) or 40)
        bell.periods_before_short_break = int(
            request.POST.get('periods_before_short_break', 3) or 3
        )
        bell.short_break_minutes = int(request.POST.get('short_break_minutes', 15) or 15)
        bell.periods_before_long_break = int(
            request.POST.get('periods_before_long_break', 2) or 2
        )
        bell.long_break_minutes = int(request.POST.get('long_break_minutes', 40) or 40)
        bell.periods_before_lesson_break = int(
            request.POST.get('periods_before_lesson_break', 3) or 3
        )
        bell.lesson_break_minutes = int(request.POST.get('lesson_break_minutes', 20) or 20)
        bell.periods_after_lesson_break = int(
            request.POST.get('periods_after_lesson_break', 2) or 2
        )
        bell.friday_periods = int(request.POST.get('friday_periods', 5) or 5)
        bell.min_periods_weekday = int(request.POST.get('min_periods_weekday', 6) or 6)
        bell.wednesday_p1_is_sport = request.POST.get('wednesday_p1_is_sport') == 'on'
        bell.wednesday_activity = (
            request.POST.get('wednesday_activity', 'Sport').strip() or 'Sport'
        )
        bell.save()
        n = rebuild_time_slots(bell)
        messages.success(
            request,
            f'Bell saved and {n} periods rebuilt. Re-generate the timetable.',
        )
        return redirect('slots')

    return render(
        request,
        'timetable/slots.html',
        {
            'slots': TimeSlot.objects.all(),
            'bell': bell,
            'days': DayOfWeek.choices,
        },
    )


def delete_slot(request, pk):
    return _safe_delete(request, TimeSlot, pk, 'slots', 'Time slot')


def availability_page(request):
    if request.method == 'POST':
        TeacherAvailability.objects.update_or_create(
            teacher_id=int(request.POST.get('teacher')),
            time_slot_id=int(request.POST.get('time_slot')),
            defaults={'is_preferred': request.POST.get('is_preferred') == 'on'},
        )
        messages.success(request, 'Availability saved.')
        return redirect('availability')

    return render(
        request,
        'timetable/availability.html',
        {
            'prefs': TeacherAvailability.objects.select_related('teacher', 'time_slot'),
            'teachers': Teacher.objects.all(),
            'slots': TimeSlot.objects.filter(is_break=False, is_reserved=False),
        },
    )


def delete_availability(request, pk):
    return _safe_delete(
        request, TeacherAvailability, pk, 'availability', 'Preference'
    )


def generate_page(request):
    if request.method == 'POST':
        try:
            run = generate_timetable(
                name=request.POST.get('name', '').strip(),
                population_size=int(request.POST.get('population_size', 36)),
                max_generations=int(request.POST.get('max_generations', 40)),
                crossover_prob=float(request.POST.get('crossover_prob', 0.7)),
                mutation_prob=float(request.POST.get('mutation_prob', 0.25)),
                publish=request.POST.get('publish') == 'on',
                keep_locked=request.POST.get('keep_locked') == 'on',
            )
            if run.hard_violations == 0:
                messages.success(
                    request,
                    f'{run.name}: clash-free in {run.generations_run} generations '
                    f'({run.execution_seconds}s).',
                )
            else:
                messages.warning(
                    request,
                    f'{run.name}: {run.hard_violations} hard clash(es), '
                    f'{run.soft_violations} soft. You can still adjust the grid.',
                )
            return redirect('timetable_detail', pk=run.pk)
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f'Generation failed: {exc}')
            return redirect('generate')

    return render(
        request,
        'timetable/generate.html',
        {
            'assignment_count': ClassAssignment.objects.count(),
            'slot_count': TimeSlot.objects.filter(is_break=False, is_reserved=False).count(),
            'class_count': SchoolClass.objects.count(),
            'runs': TimetableRun.objects.all()[:10],
            'has_locked': TimetableEntry.objects.filter(
                run__is_active=True, is_locked=True
            ).exists(),
            'load_issues': teacher_load_issues(),
        },
    )


def _grid_context(run: TimetableRun, view: str, focus_id: int | None):
    entries = list(
        run.entries.select_related('school_class', 'subject', 'teacher', 'time_slot')
    )
    days = [d[0] for d in DayOfWeek.choices]
    all_slots = list(TimeSlot.objects.all())
    sequences = sorted({s.sequence for s in all_slots})
    if not sequences:
        sequences = list(range(1, 9))

    row_titles = {}
    row_labels = {}
    monday_slots = [s for s in all_slots if s.day == 'Monday'] or all_slots
    for slot in monday_slots:
        if slot.sequence in row_titles:
            continue
        if slot.is_break:
            row_titles[slot.sequence] = slot.get_kind_display()
        elif slot.is_reserved:
            row_titles[slot.sequence] = f'P{slot.period} {slot.activity_name}'
        else:
            row_titles[slot.sequence] = f'P{slot.period}'
        row_labels[slot.sequence] = (
            f'{slot.start_time.strftime("%H:%M")}–{slot.end_time.strftime("%H:%M")}'
        )

    classes = sorted(
        {e.school_class for e in entries} | set(SchoolClass.objects.all()),
        key=lambda c: c.sort_key,
    )
    teachers = sorted({e.teacher for e in entries}, key=lambda t: t.name)

    if view == 'teacher':
        if focus_id:
            focus = next((t for t in teachers if t.id == focus_id), teachers[0] if teachers else None)
        else:
            focus = teachers[0] if teachers else None
        filtered = [e for e in entries if focus and e.teacher_id == focus.id]
    else:
        if focus_id:
            focus = next((c for c in classes if c.id == focus_id), classes[0] if classes else None)
        else:
            focus = classes[0] if classes else None
        filtered = [e for e in entries if focus and e.school_class_id == focus.id]
        view = 'class'

    grid = {day: {seq: [] for seq in sequences} for day in days}
    for e in filtered:
        grid[e.time_slot.day][e.time_slot.sequence].append(e)

    slot_ids = {day: {} for day in days}
    break_map = {day: {} for day in days}
    reserved_map = {day: {} for day in days}
    activity_map = {day: {} for day in days}
    kind_map = {day: {} for day in days}
    for slot in all_slots:
        slot_ids[slot.day][slot.sequence] = slot.id
        break_map[slot.day][slot.sequence] = slot.is_break
        reserved_map[slot.day][slot.sequence] = slot.is_reserved
        activity_map[slot.day][slot.sequence] = slot.activity_name
        kind_map[slot.day][slot.sequence] = slot.get_kind_display()

    return {
        'days': days,
        'periods': sequences,
        'period_labels': row_labels,
        'row_titles': row_titles,
        'grid': grid,
        'entries': entries,
        'filtered_entries': filtered,
        'classes': classes,
        'teachers': teachers,
        'view': view,
        'focus': focus,
        'slot_ids': slot_ids,
        'break_map': break_map,
        'reserved_map': reserved_map,
        'activity_map': activity_map,
        'kind_map': kind_map,
        'all_slots': list(
            TimeSlot.objects.filter(is_break=False, is_reserved=False)
        ),
    }


def timetable_list(request):
    return render(
        request,
        'timetable/timetable_list.html',
        {'runs': TimetableRun.objects.all()},
    )


def timetable_detail(request, pk):
    run = get_object_or_404(TimetableRun, pk=pk)
    view = request.GET.get('view', 'class')
    focus_raw = request.GET.get('focus')
    focus_id = int(focus_raw) if focus_raw and str(focus_raw).isdigit() else None
    _hard, _soft, clash_notes = count_run_violations(run)
    context = {
        'run': run,
        'clash_notes': clash_notes,
        **_grid_context(run, view, focus_id),
    }
    return render(request, 'timetable/timetable_detail.html', context)


def timetable_active(request):
    run = TimetableRun.objects.filter(is_active=True).first()
    if not run:
        messages.info(request, 'No published timetable yet. Generate one first.')
        return redirect('generate')
    return redirect('timetable_detail', pk=run.pk)


@require_POST
def adjust_move(request, pk):
    run = get_object_or_404(TimetableRun, pk=pk)
    entry = get_object_or_404(TimetableEntry, pk=request.POST.get('entry_id'), run=run)
    new_slot = get_object_or_404(TimeSlot, pk=request.POST.get('time_slot_id'))
    force = request.POST.get('force') == '1'
    move_group = request.POST.get('move_group', '1') == '1'
    ok, reasons = move_entry(entry, new_slot, force=force, move_group=move_group)
    run.refresh_from_db()
    return JsonResponse(
        {
            'ok': ok,
            'reasons': reasons,
            'hard_violations': run.hard_violations,
            'soft_violations': run.soft_violations,
            'message': run.message,
            'forced': force and ok,
        }
    )


@require_POST
def adjust_swap(request, pk):
    run = get_object_or_404(TimetableRun, pk=pk)
    entry_a = get_object_or_404(TimetableEntry, pk=request.POST.get('entry_a'), run=run)
    entry_b = get_object_or_404(TimetableEntry, pk=request.POST.get('entry_b'), run=run)
    force = request.POST.get('force') == '1'
    move_group = request.POST.get('move_group', '1') == '1'
    ok, reasons = swap_entries(entry_a, entry_b, force=force, move_group=move_group)
    run.refresh_from_db()
    return JsonResponse(
        {
            'ok': ok,
            'reasons': reasons,
            'hard_violations': run.hard_violations,
            'soft_violations': run.soft_violations,
            'message': run.message,
            'forced': force and ok,
        }
    )


@require_POST
def adjust_lock(request, pk):
    run = get_object_or_404(TimetableRun, pk=pk)
    entry = get_object_or_404(TimetableEntry, pk=request.POST.get('entry_id'), run=run)
    locked = request.POST.get('locked') == '1'
    set_entry_lock(entry, locked, move_group=request.POST.get('move_group', '1') == '1')
    return JsonResponse({'ok': True, 'locked': locked})


@require_POST
def rescore_run(request, pk):
    run = get_object_or_404(TimetableRun, pk=pk)
    refresh_run_score(run)
    messages.success(
        request,
        f'Re-checked: {run.hard_violations} hard clash(es), {run.soft_violations} soft.',
    )
    return redirect('timetable_detail', pk=run.pk)


def export_timetable(request, pk):
    run = get_object_or_404(TimetableRun, pk=pk)
    entries = run.entries.select_related(
        'school_class', 'subject', 'teacher', 'time_slot'
    ).order_by('school_class__level', 'time_slot__day', 'time_slot__period')

    wb = Workbook()
    ws = wb.active
    ws.title = 'All classes'
    ws.append(
        [
            'Class',
            'Day',
            'Period',
            'Time',
            'Subject',
            'Teacher',
            'Locked',
            'Manual',
        ]
    )
    for e in entries:
        ws.append(
            [
                str(e.school_class),
                e.time_slot.day,
                e.time_slot.period,
                e.time_slot.label,
                e.subject.name,
                e.teacher.name,
                'Yes' if e.is_locked else '',
                'Yes' if e.is_manual else '',
            ]
        )

    classes = sorted({e.school_class for e in entries}, key=lambda c: c.sort_key)
    days = [d[0] for d in DayOfWeek.choices]
    periods = sorted(set(TimeSlot.objects.values_list('period', flat=True)))
    for school_class in classes:
        sheet = wb.create_sheet(str(school_class)[:31])
        sheet.append(['Period'] + days)
        class_entries = [e for e in entries if e.school_class_id == school_class.id]
        for period in periods:
            row = [f'P{period}']
            for day in days:
                cell_items = [
                    e
                    for e in class_entries
                    if e.time_slot.day == day and e.time_slot.period == period
                ]
                row.append(
                    ' / '.join(
                        f'{e.subject.code} ({e.teacher.name})' for e in cell_items
                    )
                )
            sheet.append(row)

    response = HttpResponse(
        content_type=(
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    )
    filename = (run.name or 'timetable').replace(' ', '_')
    response['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'
    wb.save(response)
    return response


def export_pdf(request, pk):
    run = get_object_or_404(TimetableRun, pk=pk)
    from .pdf import build_timetable_pdf

    pdf = build_timetable_pdf(run)
    response = HttpResponse(pdf, content_type='application/pdf')
    filename = (run.name or 'timetable').replace(' ', '_')
    response['Content-Disposition'] = f'attachment; filename="{filename}.pdf"'
    return response


def print_sheet(request, pk):
    run = get_object_or_404(TimetableRun, pk=pk)
    return render(request, 'timetable/print_sheet.html', school_sheet_context(run))


def publish_run(request, pk):
    run = get_object_or_404(TimetableRun, pk=pk)
    run.is_active = True
    run.save()
    messages.success(request, f'{run.name} is now the published timetable.')
    return redirect('timetable_detail', pk=pk)


def delete_run(request, pk):
    return _safe_delete(request, TimetableRun, pk, 'timetable_list', 'Timetable')
