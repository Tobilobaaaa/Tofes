from django.db import migrations, models


def lower_min_periods(apps, schema_editor):
    BellSettings = apps.get_model('timetable', 'BellSettings')
    BellSettings.objects.filter(min_periods_weekday__gt=6).update(min_periods_weekday=6)


class Migration(migrations.Migration):

    dependencies = [
        ('timetable', '0003_bell_print_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='bellsettings',
            name='min_periods_weekday',
            field=models.PositiveIntegerField(
                default=6,
                help_text='Minimum teaching periods per class Mon–Thu (Sport on Wednesday counts). 6–7 is enough; 8 is welcome when it fits.',
            ),
        ),
        migrations.AlterField(
            model_name='simultaneousgroup',
            name='periods_per_week',
            field=models.PositiveIntegerField(
                default=3,
                help_text='Typical shared slots. Each subject can have its own periods/week; extra slots leave other streams free.',
            ),
        ),
        migrations.AlterField(
            model_name='timetablerun',
            name='max_generations',
            field=models.PositiveIntegerField(default=40),
        ),
        migrations.AlterField(
            model_name='timetablerun',
            name='population_size',
            field=models.PositiveIntegerField(default=36),
        ),
        migrations.RunPython(lower_min_periods, migrations.RunPython.noop),
    ]
