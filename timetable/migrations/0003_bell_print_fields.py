from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('timetable', '0002_bell_and_simultaneous'),
    ]

    operations = [
        migrations.AddField(
            model_name='bellsettings',
            name='school_name',
            field=models.CharField(default='TOFES EXCELLENCE COLLEGE', max_length=160),
        ),
        migrations.AddField(
            model_name='bellsettings',
            name='term_title',
            field=models.CharField(default='THIRD TERM 2025/2026', max_length=120),
        ),
        migrations.AddField(
            model_name='bellsettings',
            name='assembly_time',
            field=models.CharField(default='7:45 - 8:15', max_length=40),
        ),
        migrations.AddField(
            model_name='bellsettings',
            name='attendance_time',
            field=models.CharField(default='8:15 - 8:30', max_length=40),
        ),
        migrations.AddField(
            model_name='bellsettings',
            name='friday_club_time',
            field=models.CharField(default='12:00 - 12:30', max_length=40),
        ),
        migrations.AddField(
            model_name='bellsettings',
            name='friday_club_label',
            field=models.CharField(default='CLUB ACTIVITIES', max_length=40),
        ),
        migrations.AddField(
            model_name='bellsettings',
            name='friday_fellowship_time',
            field=models.CharField(default='12:30 - 1:00', max_length=40),
        ),
        migrations.AddField(
            model_name='bellsettings',
            name='friday_fellowship_label',
            field=models.CharField(default='FELLOWSHIP', max_length=40),
        ),
    ]
