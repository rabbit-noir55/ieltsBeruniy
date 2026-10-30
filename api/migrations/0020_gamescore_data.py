# GameScore.stats (JSON) -> data (TextField): server faqat xotira
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0019_game_gamesession_gamescore'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='gamescore',
            name='stats',
        ),
        migrations.AddField(
            model_name='gamescore',
            name='data',
            field=models.TextField(blank=True, default=''),
        ),
    ]
