from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0014_remove_ai_fields'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "DROP TABLE IF EXISTS api_newsread",
                "DROP TABLE IF EXISTS api_newscomment",
                "DROP TABLE IF EXISTS api_newsreaction",
                "DROP TABLE IF EXISTS api_news",
            ],
            reverse_sql=[],
        ),
    ]
