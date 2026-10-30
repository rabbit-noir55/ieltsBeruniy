# Guruh logotipi bazada (data URL) saqlanadi
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0017_mocktest_mockpreview'),
    ]

    operations = [
        migrations.AddField(
            model_name='usergroup',
            name='logo_data',
            field=models.TextField(blank=True, default=''),
        ),
    ]
