from datetime import time

from django.db import models


class DayOfWeek(models.TextChoices):
    MONDAY = 'Monday', 'Monday'
    TUESDAY = 'Tuesday', 'Tuesday'
    WEDNESDAY = 'Wednesday', 'Wednesday'
    THURSDAY = 'Thursday', 'Thursday'
    FRIDAY = 'Friday', 'Friday'


class Section(models.TextChoices):
    JUNIOR = 'junior', 'Junior (JSS 1–3)'
    SENIOR = 'senior', 'Senior (SS 1–3)'
    BOTH = 'both', 'Junior and Senior'


class ClassLevel(models.TextChoices):
    JSS1 = 'JSS1', 'JSS 1'
    JSS2 = 'JSS2', 'JSS 2'
    JSS3 = 'JSS3', 'JSS 3'
    SS1 = 'SS1', 'SS 1'
    SS2 = 'SS2', 'SS 2'
    SS3 = 'SS3', 'SS 3'


JUNIOR_LEVELS = {ClassLevel.JSS1, ClassLevel.JSS2, ClassLevel.JSS3}
SENIOR_LEVELS = {ClassLevel.SS1, ClassLevel.SS2, ClassLevel.SS3}

LEVEL_ORDER = {
    ClassLevel.JSS1: 1,
    ClassLevel.JSS2: 2,
    ClassLevel.JSS3: 3,
    ClassLevel.SS1: 4,
    ClassLevel.SS2: 5,
    ClassLevel.SS3: 6,
}


class Teacher(models.Model):
    name = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    notes = models.CharField(
        max_length=200,
        blank=True,
        help_text='e.g. Civic (JSS 1–3) only',
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def subject_count(self):
        return self.can_teach.count()


class SimultaneousGroup(models.Model):
    """Subjects taught at the same time (students split by stream)."""

    name = models.CharField(max_length=120)
    section = models.CharField(
        max_length=10,
        choices=Section.choices,
        default=Section.SENIOR,
    )
    periods_per_week = models.PositiveIntegerField(
        default=3,
        help_text='Typical shared slots. Each subject can have its own periods/week; extra slots leave other streams free.',
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        codes = ', '.join(s.code for s in self.subjects.all())
        return f'{self.name} ({codes})' if codes else self.name


class Subject(models.Model):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20, unique=True)
    section = models.CharField(
        max_length=10,
        choices=Section.choices,
        default=Section.JUNIOR,
    )
    simultaneous_group = models.ForeignKey(
        SimultaneousGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subjects',
        help_text='Leave empty if this subject has its own periods.',
    )
    default_periods = models.PositiveIntegerField(
        default=2,
        help_text='Typical periods per week when assigning to a class.',
    )

    class Meta:
        ordering = ['section', 'name']

    def __str__(self):
        return f'{self.code} — {self.name}'

    @property
    def option_group(self):
        return self.simultaneous_group.name if self.simultaneous_group_id else ''


class SchoolClass(models.Model):
    level = models.CharField(max_length=8, choices=ClassLevel.choices)
    arm = models.CharField(
        max_length=8,
        blank=True,
        help_text='Optional arm, e.g. A, B. Leave blank if the school has one stream per level.',
    )

    class Meta:
        ordering = ['level', 'arm']
        unique_together = [('level', 'arm')]
        verbose_name = 'class'
        verbose_name_plural = 'classes'

    def __str__(self):
        label = self.get_level_display()
        return f'{label}{self.arm}' if self.arm else label

    @property
    def sheet_label(self):
        return f'{self.level}{self.arm}' if self.arm else self.level

    @property
    def section(self):
        if self.level in JUNIOR_LEVELS:
            return Section.JUNIOR
        return Section.SENIOR

    @property
    def sort_key(self):
        return (LEVEL_ORDER.get(self.level, 99), self.arm or '')


class TeacherSubject(models.Model):
    """A teacher may take 3–4 subjects across junior and senior."""

    teacher = models.ForeignKey(
        Teacher, on_delete=models.CASCADE, related_name='can_teach'
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name='teachers'
    )
    section_scope = models.CharField(
        max_length=10,
        choices=Section.choices,
        default=Section.BOTH,
        help_text='Limit this assignment to junior, senior, or both.',
    )

    class Meta:
        unique_together = [('teacher', 'subject', 'section_scope')]
        verbose_name = 'teacher subject'
        verbose_name_plural = 'teacher subjects'

    def __str__(self):
        return f'{self.teacher} → {self.subject.code} ({self.section_scope})'

    def covers_class(self, school_class: 'SchoolClass') -> bool:
        if self.section_scope == Section.BOTH:
            return True
        return self.section_scope == school_class.section


class ClassAssignment(models.Model):
    """Who teaches a subject to a class, and how many periods per week."""

    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.CASCADE, related_name='assignments'
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name='assignments'
    )
    teacher = models.ForeignKey(
        Teacher, on_delete=models.PROTECT, related_name='assignments'
    )
    periods_per_week = models.PositiveIntegerField(default=2)

    class Meta:
        unique_together = [('school_class', 'subject')]
        ordering = ['school_class', 'subject__name']

    def __str__(self):
        return f'{self.school_class} · {self.subject.code} · {self.teacher}'


class SlotKind(models.TextChoices):
    TEACHING = 'teaching', 'Teaching period'
    SHORT_BREAK = 'short_break', 'Short break'
    LONG_BREAK = 'long_break', 'Long break'
    LESSON_BREAK = 'lesson_break', 'Lesson break'
    RESERVED = 'reserved', 'Reserved (e.g. Sport)'


class BellSettings(models.Model):
    """Singleton: school day shape. Change these, then rebuild periods."""

    school_name = models.CharField(max_length=160, default='TOFES EXCELLENCE COLLEGE')
    term_title = models.CharField(max_length=120, default='THIRD TERM 2025/2026')
    assembly_time = models.CharField(max_length=40, default='7:45 - 8:15')
    attendance_time = models.CharField(max_length=40, default='8:15 - 8:30')
    friday_club_time = models.CharField(max_length=40, default='12:00 - 12:30')
    friday_club_label = models.CharField(max_length=40, default='CLUB ACTIVITIES')
    friday_fellowship_time = models.CharField(max_length=40, default='12:30 - 1:00')
    friday_fellowship_label = models.CharField(max_length=40, default='FELLOWSHIP')
    start_time = models.TimeField(default=time(8, 30))
    period_minutes = models.PositiveIntegerField(default=40)
    periods_before_short_break = models.PositiveIntegerField(default=3)
    short_break_minutes = models.PositiveIntegerField(default=15)
    periods_before_long_break = models.PositiveIntegerField(default=2)
    long_break_minutes = models.PositiveIntegerField(default=40)
    periods_before_lesson_break = models.PositiveIntegerField(default=3)
    lesson_break_minutes = models.PositiveIntegerField(default=20)
    periods_after_lesson_break = models.PositiveIntegerField(default=2)
    friday_periods = models.PositiveIntegerField(
        default=5,
        help_text='Teaching periods on Friday (Mon–Thu use the full 10).',
    )
    min_periods_weekday = models.PositiveIntegerField(
        default=6,
        help_text='Minimum teaching periods per class Mon–Thu (Sport on Wednesday counts). 6–7 is enough; 8 is welcome when it fits.',
    )
    wednesday_p1_is_sport = models.BooleanField(
        default=True,
        help_text='Wednesday first period is Sport for every class.',
    )
    wednesday_activity = models.CharField(max_length=40, default='Sport')

    class Meta:
        verbose_name = 'bell settings'
        verbose_name_plural = 'bell settings'

    def __str__(self):
        return 'School bell settings'

    @classmethod
    def load(cls):
        obj = cls.objects.first()
        if obj:
            return obj
        return cls.objects.create()

    @property
    def weekday_periods(self):
        return (
            self.periods_before_short_break
            + self.periods_before_long_break
            + self.periods_before_lesson_break
            + self.periods_after_lesson_break
        )

    @property
    def first_period_after_long_break(self):
        return self.periods_before_short_break + self.periods_before_long_break + 1


class TimeSlot(models.Model):
    day = models.CharField(max_length=10, choices=DayOfWeek.choices)
    sequence = models.PositiveIntegerField(
        default=1, help_text='Row order including breaks'
    )
    period = models.PositiveIntegerField(
        default=0,
        help_text='Teaching period number (1–10). 0 for breaks.',
    )
    start_time = models.TimeField()
    end_time = models.TimeField()
    label = models.CharField(max_length=60, blank=True)
    kind = models.CharField(
        max_length=20, choices=SlotKind.choices, default=SlotKind.TEACHING
    )
    is_break = models.BooleanField(default=False)
    is_reserved = models.BooleanField(
        default=False,
        help_text='Blocked for a whole-school activity (Wednesday Sport).',
    )
    activity_name = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = [
            models.Case(
                models.When(day='Monday', then=0),
                models.When(day='Tuesday', then=1),
                models.When(day='Wednesday', then=2),
                models.When(day='Thursday', then=3),
                models.When(day='Friday', then=4),
                default=5,
            ),
            'sequence',
        ]
        unique_together = [('day', 'sequence')]

    def __str__(self):
        if self.label:
            return self.label
        return f'{self.day} seq{self.sequence}'

    @property
    def is_teachable(self):
        return not self.is_break and not self.is_reserved

    def save(self, *args, **kwargs):
        if not self.label:
            time_bit = (
                f'{self.start_time.strftime("%H:%M")}-{self.end_time.strftime("%H:%M")}'
            )
            if self.is_break:
                self.label = f'{self.day[:3]} {self.get_kind_display()} {time_bit}'
            elif self.is_reserved:
                act = self.activity_name or 'Reserved'
                self.label = f'{self.day[:3]} P{self.period} {act} {time_bit}'
            else:
                self.label = f'{self.day[:3]} P{self.period} {time_bit}'
        super().save(*args, **kwargs)


class TeacherAvailability(models.Model):
    teacher = models.ForeignKey(
        Teacher, on_delete=models.CASCADE, related_name='availabilities'
    )
    time_slot = models.ForeignKey(
        TimeSlot, on_delete=models.CASCADE, related_name='teacher_prefs'
    )
    is_preferred = models.BooleanField(
        default=True,
        help_text='On = preferred. Off = teacher is unavailable at this slot.',
    )

    class Meta:
        unique_together = [('teacher', 'time_slot')]
        verbose_name_plural = 'teacher availabilities'

    def __str__(self):
        pref = 'prefers' if self.is_preferred else 'unavailable'
        return f'{self.teacher} {pref} {self.time_slot}'


class TimetableRun(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RUNNING = 'running', 'Running'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    name = models.CharField(max_length=120, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    population_size = models.PositiveIntegerField(default=36)
    max_generations = models.PositiveIntegerField(default=40)
    crossover_prob = models.FloatField(default=0.7)
    mutation_prob = models.FloatField(default=0.25)
    generations_run = models.PositiveIntegerField(default=0)
    best_fitness = models.FloatField(null=True, blank=True)
    hard_violations = models.PositiveIntegerField(default=0)
    soft_violations = models.PositiveIntegerField(default=0)
    execution_seconds = models.FloatField(null=True, blank=True)
    fitness_history = models.JSONField(default=list, blank=True)
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(
        default=False, help_text='Currently published timetable'
    )
    keep_locked = models.BooleanField(
        default=False,
        help_text='This run preserved locked lessons from the previous published timetable.',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        label = self.name or f'Run #{self.pk}'
        return f'{label} ({self.status})'

    def save(self, *args, **kwargs):
        if self.is_active:
            TimetableRun.objects.filter(is_active=True).exclude(pk=self.pk).update(
                is_active=False
            )
        if not self.name and self.pk:
            self.name = f'Timetable #{self.pk}'
        super().save(*args, **kwargs)


class TimetableEntry(models.Model):
    run = models.ForeignKey(
        TimetableRun, on_delete=models.CASCADE, related_name='entries'
    )
    school_class = models.ForeignKey(SchoolClass, on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    time_slot = models.ForeignKey(TimeSlot, on_delete=models.CASCADE)
    session_index = models.PositiveIntegerField(default=1)
    option_group = models.CharField(max_length=40, blank=True)
    is_locked = models.BooleanField(
        default=False,
        help_text='Keep this lesson here when regenerating with “keep locked”.',
    )
    is_manual = models.BooleanField(
        default=False,
        help_text='Moved or swapped by a person after generation.',
    )

    class Meta:
        ordering = [
            'school_class__level',
            'time_slot__day',
            'time_slot__period',
            'subject__code',
        ]
        verbose_name_plural = 'timetable entries'

    def __str__(self):
        return f'{self.school_class} {self.subject.code} @ {self.time_slot}'
