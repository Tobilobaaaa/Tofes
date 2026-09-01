from django.contrib import admin

from .models import (
    BellSettings,
    ClassAssignment,
    SchoolClass,
    SimultaneousGroup,
    Subject,
    Teacher,
    TeacherAvailability,
    TeacherSubject,
    TimeSlot,
    TimetableEntry,
    TimetableRun,
)


class TeacherSubjectInline(admin.TabularInline):
    model = TeacherSubject
    extra = 1


class ClassAssignmentInline(admin.TabularInline):
    model = ClassAssignment
    extra = 0


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone', 'subject_count')
    search_fields = ('name', 'email')
    inlines = [TeacherSubjectInline]


@admin.register(SimultaneousGroup)
class SimultaneousGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'section', 'periods_per_week')


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'section', 'simultaneous_group', 'default_periods')
    list_filter = ('section', 'simultaneous_group')
    search_fields = ('code', 'name')


@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ('level', 'arm')
    list_filter = ('level',)
    inlines = [ClassAssignmentInline]


@admin.register(TeacherSubject)
class TeacherSubjectAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'subject', 'section_scope')
    list_filter = ('section_scope',)


@admin.register(ClassAssignment)
class ClassAssignmentAdmin(admin.ModelAdmin):
    list_display = ('school_class', 'subject', 'teacher', 'periods_per_week')
    list_filter = ('school_class', 'subject')


@admin.register(BellSettings)
class BellSettingsAdmin(admin.ModelAdmin):
    list_display = (
        'school_name',
        'term_title',
        'start_time',
        'period_minutes',
        'friday_periods',
        'wednesday_activity',
    )


@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = ('label', 'day', 'sequence', 'period', 'start_time', 'end_time', 'kind', 'is_reserved')
    list_filter = ('day', 'kind', 'is_reserved')


@admin.register(TeacherAvailability)
class TeacherAvailabilityAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'time_slot', 'is_preferred')
    list_filter = ('is_preferred',)


class TimetableEntryInline(admin.TabularInline):
    model = TimetableEntry
    extra = 0
    readonly_fields = (
        'school_class',
        'subject',
        'teacher',
        'time_slot',
        'session_index',
        'option_group',
        'is_locked',
        'is_manual',
    )


@admin.register(TimetableRun)
class TimetableRunAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'status',
        'hard_violations',
        'soft_violations',
        'generations_run',
        'execution_seconds',
        'is_active',
        'created_at',
    )
    list_filter = ('status', 'is_active')
    inlines = [TimetableEntryInline]


@admin.register(TimetableEntry)
class TimetableEntryAdmin(admin.ModelAdmin):
    list_display = (
        'run',
        'school_class',
        'subject',
        'teacher',
        'time_slot',
        'is_locked',
        'is_manual',
    )
    list_filter = ('run', 'is_locked', 'is_manual')
