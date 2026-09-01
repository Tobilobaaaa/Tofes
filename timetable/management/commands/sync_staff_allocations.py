"""
Apply the current TOFES teacher–subject allocation without wiping bell times or classes.

Usage:
    python manage.py sync_staff_allocations
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from timetable.models import (
    ClassAssignment,
    SchoolClass,
    Section,
    SimultaneousGroup,
    Subject,
    Teacher,
    TeacherSubject,
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
from timetable.services import refresh_group_period_hint


class Command(BaseCommand):
    help = 'Update teachers and class assignments to the current staff list.'

    @transaction.atomic
    def handle(self, *args, **options):
        TimetableRun.objects.all().delete()
        ClassAssignment.objects.all().delete()

        self._ensure_catalog_subjects()

        teachers: dict[str, Teacher] = {}
        for name, notes in TEACHER_NOTES.items():
            teacher, _ = Teacher.objects.update_or_create(
                name=name,
                defaults={'notes': notes},
            )
            teachers[name] = teacher

        TeacherSubject.objects.all().delete()
        subjects = {s.code: s for s in Subject.objects.all()}
        missing = []
        for teacher_name, code, scope in TEACHER_SUBJECTS:
            subject = subjects.get(code)
            if subject is None:
                missing.append(code)
                continue
            TeacherSubject.objects.create(
                teacher=teachers[teacher_name],
                subject=subject,
                section_scope=scope,
            )
        if missing:
            self.stdout.write(self.style.WARNING(f'Missing subjects (skipped): {missing}'))

        links = [
            (teachers[n], subjects[c], scope)
            for n, c, scope in TEACHER_SUBJECTS
            if c in subjects
        ]

        def teacher_for(class_level, code):
            override = CLASS_OVERRIDES.get((class_level, code))
            if override:
                return teachers.get(override)
            school_class = SchoolClass(level=class_level, arm='')
            for person, subject, scope in links:
                if subject.code != code:
                    continue
                dummy = TeacherSubject(teacher=person, subject=subject, section_scope=scope)
                if dummy.covers_class(school_class):
                    return person
            return None

        assigned = 0
        for school_class in SchoolClass.objects.all():
            codes = (
                [row[0] for row in JUNIOR_SUBJECTS]
                if school_class.level in JUNIOR_LEVELS
                else [row[0] for row in SENIOR_STANDALONE]
                + [row[0] for row in SENIOR_SIMULTANEOUS]
            )
            for code in codes:
                subject = subjects.get(code)
                if subject is None:
                    continue
                person = teacher_for(school_class.level, code)
                if person is None:
                    continue
                ClassAssignment.objects.create(
                    school_class=school_class,
                    subject=subject,
                    teacher=person,
                    periods_per_week=subject.default_periods,
                )
                assigned += 1

        for group in SimultaneousGroup.objects.all():
            refresh_group_period_hint(group)

        self.stdout.write(self.style.SUCCESS(
            f'Staff synced: {Teacher.objects.count()} teachers, {assigned} class assignments. '
            f'Old timetable runs cleared — generate a new one.'
        ))

    def _ensure_catalog_subjects(self):
        """Create or refresh subjects from the shared catalog."""
        for code, name, periods in JUNIOR_SUBJECTS:
            Subject.objects.update_or_create(
                code=code,
                defaults={
                    'name': name,
                    'section': Section.JUNIOR,
                    'default_periods': periods,
                    'simultaneous_group': None,
                },
            )
        for code, name, periods in SENIOR_STANDALONE:
            Subject.objects.update_or_create(
                code=code,
                defaults={
                    'name': name,
                    'section': Section.SENIOR,
                    'default_periods': periods,
                    'simultaneous_group': None,
                },
            )

        groups: dict[str, SimultaneousGroup] = {}
        for _code, _name, group_name, periods in SENIOR_SIMULTANEOUS:
            if group_name not in groups:
                group, _ = SimultaneousGroup.objects.get_or_create(
                    name=group_name,
                    defaults={
                        'section': Section.SENIOR,
                        'periods_per_week': periods,
                    },
                )
                groups[group_name] = group

        for code, name, group_name, periods in SENIOR_SIMULTANEOUS:
            Subject.objects.update_or_create(
                code=code,
                defaults={
                    'name': name,
                    'section': Section.SENIOR,
                    'default_periods': periods,
                    'simultaneous_group': groups[group_name],
                },
            )
