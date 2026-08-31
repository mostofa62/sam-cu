from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('allocations', '0006_alter_hallallocation_options_and_more'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='hallallocation',
            name='unique_student_across_calls',
        ),
        migrations.AlterField(
            model_name='hallallocation',
            name='student_id',
            field=models.CharField(db_index=True, help_text='Student who received this allotment.', max_length=10),
        ),
        migrations.AddConstraint(
            model_name='hallallocation',
            constraint=models.UniqueConstraint(fields=('call', 'student_id'), name='unique_student_per_call'),
        ),
    ]
