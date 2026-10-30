# icon: emoji yoki inline SVG (CharField -> TextField)
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0022_game_icon_colors'),
    ]

    operations = [
        migrations.AlterField(
            model_name='game',
            name='icon',
            field=models.TextField(blank=True, default=''),
        ),
    ]
