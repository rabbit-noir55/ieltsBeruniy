# Ustoz qo'shadigan o'yinlar (sandbox HTML) + universal leaderboard
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0018_usergroup_logo_data'),
    ]

    operations = [
        migrations.CreateModel(
            name='Game',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=150)),
                ('description', models.CharField(blank=True, default='', max_length=300)),
                ('html_code', models.TextField()),
                ('config', models.JSONField(blank=True, default=dict)),
                ('is_active', models.BooleanField(default=True)),
                ('order', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_games', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['order', 'id']},
        ),
        migrations.CreateModel(
            name='GameSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(db_index=True, max_length=48, unique=True)),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('game', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sessions', to='api.game')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='game_sessions', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-started_at']},
        ),
        migrations.CreateModel(
            name='GameScore',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('score', models.FloatField()),
                ('stats', models.JSONField(blank=True, default=dict)),
                ('duration_ms', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('game', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='scores', to='api.game')),
                ('session', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='score', to='api.gamesession')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='game_scores', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-score', 'created_at']},
        ),
        migrations.AddConstraint(
            model_name='gamescore',
            constraint=models.UniqueConstraint(fields=('game', 'session'), name='unique_game_session_score'),
        ),
    ]
