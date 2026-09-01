"""
Seed JSS 1–SS 3, simultaneous senior blocks, sample teachers, and the school bell.

Usage:
    python manage.py seed_school_data
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from timetable.models import (
    BellSettings,
    ClassAssignment,
    ClassLevel,
    SchoolClass,
    Section,
    SimultaneousGroup,
    Subject,
    Teacher,
    TeacherAvailability,
    TeacherSubject,
    TimeSlot,
    TimetableRun,
)
from timetable.school_catalog import (
    CLASS_OVERRIDES,
    JUNIOR_LEVELS,
    JUNIOR_SUBJECTS,
    SENIOR_SIMULTANEOUS,
    SENIOR_STANDALONE,
    TEACHER_NOTES,
    TEACHER_SUBJECTS,
)
from timetable.services import rebuild_time_slots


class Command(BaseCommand):
    help = 'Load JSS 1–SS 3 classes, subjects, simultaneous groups, teachers and bell times.'

    @transaction.atomic
    def handle(self, *args, **options):
        if ClassAssignment.objects.exists() or Teacher.objects.exists():
            self.stdout.write(self.style.WARNING('Clearing existing school data…'))
            TimetableRun.objects.all().delete()
            ClassAssignment.objects.all().delete()
            TeacherAvailability.objects.all().delete()
            TeacherSubject.objects.all().delete()
            TimeSlot.objects.all().delete()
            SchoolClass.objects.all().delete()
            Subject.objects.all().delete()
            SimultaneousGroup.objects.all().delete()
            Teacher.objects.all().delete()
            BellSettings.objects.all().delete()

        bell = BellSettings.objects.create()
        n_slots = rebuild_time_slots(bell)

        groups: dict[str, SimultaneousGroup] = {}
        for _code, _name, group_name, periods in SENIOR_SIMULTANEOUS:
            if group_name not in groups:
                groups[group_name] = SimultaneousGroup.objects.create(
                    name=group_name,
                    section=Section.SENIOR,
                    periods_per_week=periods,
                )

        subjects = {}
        for code, name, periods in JUNIOR_SUBJECTS:
            subjects[code] = Subject.objects.create(
                code=code,
                name=name,
                section=Section.JUNIOR,
                default_periods=periods,
            )
        for code, name, periods in SENIOR_STANDALONE:
            subjects[code] = Subject.objects.create(
                code=code,
                name=name,
                section=Section.SENIOR,
                default_periods=periods,
            )
        for code, name, group_name, periods in SENIOR_SIMULTANEOUS:
            subjects[code] = Subject.objects.create(
                code=code,
                name=name,
                section=Section.SENIOR,
                simultaneous_group=groups[group_name],
                default_periods=periods,
            )

        classes = {
            level: SchoolClass.objects.create(level=level, arm='')
            for level in ClassLevel
        }

        staff = {
            name: Teacher.objects.create(name=name, notes=notes)
            for name, notes in TEACHER_NOTES.items()
        }

        links = [
            (staff[name], subjects[code], scope)
            for name, code, scope in TEACHER_SUBJECTS
        ]
        for person, subject, scope in links:
            TeacherSubject.objects.create(
                teacher=person,
                subject=subject,
                section_scope=scope,
            )

        junior_codes = [row[0] for row in JUNIOR_SUBJECTS]
        senior_codes = [row[0] for row in SENIOR_STANDALONE] + [
            row[0] for row in SENIOR_SIMULTANEOUS
        ]

        def teacher_for_subject(code, school_class):
            override_name = CLASS_OVERRIDES.get((school_class.level, code))
            if override_name:
                return staff[override_name]
            for person, subject, scope in links:
                if subject.code != code:
                    continue
                dummy = TeacherSubject(
                    teacher=person, subject=subject, section_scope=scope
                )
                if dummy.covers_class(school_class):
                    return person
            return None

        assigned = 0
        for level, school_class in classes.items():
            codes = junior_codes if level in JUNIOR_LEVELS else senior_codes
            for code in codes:
                subject = subjects[code]
                person = teacher_for_subject(code, school_class)
                if person is None:
                    continue
                ClassAssignment.objects.create(
                    school_class=school_class,
                    subject=subject,
                    teacher=person,
                    periods_per_week=subject.default_periods,
                )
                assigned += 1

        mornings = [
            s
            for s in TimeSlot.objects.filter(is_break=False, is_reserved=False)
            if s.period <= 3
        ]
        for slot in mornings[:6]:
            TeacherAvailability.objects.create(
                teacher=staff['Mr Sunday'], time_slot=slot, is_preferred=True
            )

        self.stdout.write(self.style.SUCCESS(
            f'Seeded {Teacher.objects.count()} teachers, {Subject.objects.count()} subjects, '
            f'{SimultaneousGroup.objects.count()} simultaneous groups, '
            f'{SchoolClass.objects.count()} classes, {assigned} assignments, '
            f'{n_slots} bell slots (start {bell.start_time}, {bell.period_minutes} min periods).'
        ))
