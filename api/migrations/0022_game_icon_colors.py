# O'yin kartochkasi uchun ikonka va ranglar
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0021_gameresult_drop_scores'),
    ]

    operations = [
        migrations.AddField(
            model_name='game',
            name='icon',
            field=models.CharField(blank=True, default='', max_length=16),
        ),
        migrations.AddField(
            model_name='game',
            name='colors',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
