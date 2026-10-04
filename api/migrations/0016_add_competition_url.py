from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0015_remove_news'),
    ]

    operations = [
        migrations.AddField(
            model_name='usergroup',
            name='competition_url',
            field=models.URLField(blank=True, default='', help_text='Competition Google Sheet base URL (gid sizsiz)', max_length=500),
        ),
    ]
