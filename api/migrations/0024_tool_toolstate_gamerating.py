# Tools (ustoz qo'shadi) + tool xotirasi + o'yin reytingi
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0023_game_icon_svg'),
    ]

    operations = [
        migrations.CreateModel(
            name='Tool',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=150)),
                ('description', models.CharField(blank=True, default='', max_length=300)),
                ('html_code', models.TextField()),
                ('config', models.JSONField(blank=True, default=dict)),
                ('icon', models.TextField(blank=True, default='')),
                ('colors', models.JSONField(blank=True, default=list)),
                ('is_active', models.BooleanField(default=True)),
                ('order', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_tools', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['order', 'id']},
        ),
        migrations.CreateModel(
            name='ToolState',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=120)),
                ('value', models.JSONField(blank=True, default=dict)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('tool', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='states', to='api.tool')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tool_states', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-updated_at']},
        ),
        migrations.AddConstraint(
            model_name='toolstate',
            constraint=models.UniqueConstraint(fields=('tool', 'user', 'key'), name='unique_tool_user_key'),
        ),
        migrations.CreateModel(
            name='GameRating',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rating', models.PositiveSmallIntegerField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('game', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ratings', to='api.game')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='game_ratings', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-updated_at']},
        ),
        migrations.AddConstraint(
            model_name='gamerating',
            constraint=models.UniqueConstraint(fields=('game', 'user'), name='unique_game_user_rating'),
        ),
    ]
