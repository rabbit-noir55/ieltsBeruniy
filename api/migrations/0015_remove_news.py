from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0014_remove_ai_fields'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "DROP TABLE IF EXISTS api_newsread CASCADE",
                "DROP TABLE IF EXISTS api_newscomment CASCADE",
                "DROP TABLE IF EXISTS api_newsreaction CASCADE",
                "DROP TABLE IF EXISTS api_news CASCADE",
            ],
            reverse_sql=[],
        ),
    ]
