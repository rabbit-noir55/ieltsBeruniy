from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0032_ensure_teacher_gmail_accounts'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='telegram_phone',
            field=models.CharField(
                blank=True, db_index=True, default='', max_length=20
            ),
        ),
    ]
