from django.urls import path

from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('teachers/', views.teachers_page, name='teachers'),
    path('teachers/<int:pk>/edit/', views.edit_teacher, name='edit_teacher'),
    path('teachers/<int:pk>/delete/', views.delete_teacher, name='delete_teacher'),
    path('subjects/', views.subjects_page, name='subjects'),
    path('subjects/<int:pk>/edit/', views.edit_subject, name='edit_subject'),
    path(
        'subjects/<int:pk>/periods/',
        views.update_subject_periods,
        name='update_subject_periods',
    ),
    path('subjects/<int:pk>/delete/', views.delete_subject, name='delete_subject'),
    path('simultaneous/', views.simultaneous_page, name='simultaneous'),
    path(
        'simultaneous/<int:pk>/edit/',
        views.edit_simultaneous,
        name='edit_simultaneous',
    ),
    path(
        'simultaneous/<int:pk>/delete/',
        views.delete_simultaneous,
        name='delete_simultaneous',
    ),
    path('classes/', views.classes_page, name='classes'),
    path('classes/<int:pk>/delete/', views.delete_class, name='delete_class'),
    path('assignments/', views.assignments_page, name='assignments'),
    path(
        'assignments/<int:pk>/periods/',
        views.update_assignment_periods,
        name='update_assignment_periods',
    ),
    path(
        'assignments/<int:pk>/delete/',
        views.delete_assignment,
        name='delete_assignment',
    ),
    path('slots/', views.slots_page, name='slots'),
    path('slots/<int:pk>/delete/', views.delete_slot, name='delete_slot'),
    path('availability/', views.availability_page, name='availability'),
    path(
        'availability/<int:pk>/delete/',
        views.delete_availability,
        name='delete_availability',
    ),
    path('generate/', views.generate_page, name='generate'),
    path('timetable/', views.timetable_active, name='timetable'),
    path('timetable/runs/', views.timetable_list, name='timetable_list'),
    path('timetable/<int:pk>/', views.timetable_detail, name='timetable_detail'),
    path('timetable/<int:pk>/export/', views.export_timetable, name='export_timetable'),
    path('timetable/<int:pk>/pdf/', views.export_pdf, name='export_pdf'),
    path('timetable/<int:pk>/print/', views.print_sheet, name='print_sheet'),
    path('timetable/<int:pk>/publish/', views.publish_run, name='publish_run'),
    path('timetable/<int:pk>/delete/', views.delete_run, name='delete_run'),
    path('timetable/<int:pk>/rescore/', views.rescore_run, name='rescore_run'),
    path('timetable/<int:pk>/move/', views.adjust_move, name='adjust_move'),
    path('timetable/<int:pk>/swap/', views.adjust_swap, name='adjust_swap'),
    path('timetable/<int:pk>/lock/', views.adjust_lock, name='adjust_lock'),
]
