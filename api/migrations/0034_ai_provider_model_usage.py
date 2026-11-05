from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0033_user_telegram_phone'),
    ]

    operations = [
        migrations.CreateModel(
            name='AIProvider',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80)),
                ('slug', models.SlugField(max_length=80, unique=True)),
                ('kind', models.CharField(choices=[('gemini', 'Google Gemini'), ('openai', 'OpenAI-compatible')], default='openai', max_length=20)),
                ('base_url', models.CharField(blank=True, default='', max_length=300)),
                ('api_key_env', models.CharField(blank=True, default='', max_length=200)),
                ('enabled', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['name']},
        ),
        migrations.CreateModel(
            name='AIModel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120)),
                ('model_id', models.CharField(max_length=160)),
                ('features', models.JSONField(blank=True, default=list)),
                ('priority', models.PositiveIntegerField(default=100)),
                ('enabled', models.BooleanField(default=True)),
                ('max_tokens', models.PositiveIntegerField(default=8192)),
                ('temperature', models.FloatField(default=0.7)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('provider', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='models', to='api.aiprovider')),
            ],
            options={'ordering': ['priority', 'id']},
        ),
        migrations.CreateModel(
            name='AIUsage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('feature', models.CharField(db_index=True, max_length=40)),
                ('provider', models.CharField(blank=True, default='', max_length=80)),
                ('model', models.CharField(blank=True, default='', max_length=160)),
                ('success', models.BooleanField(default=False)),
                ('tokens_in', models.PositiveIntegerField(default=0)),
                ('tokens_out', models.PositiveIntegerField(default=0)),
                ('latency_ms', models.PositiveIntegerField(default=0)),
                ('error', models.TextField(blank=True, default='')),
                ('meta', models.JSONField(blank=True, default=dict)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ai_usages', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at'], 'verbose_name_plural': 'AI usage'},
        ),
        migrations.AlterUniqueTogether(
            name='aimodel',
            unique_together={('provider', 'model_id')},
        ),
    ]
