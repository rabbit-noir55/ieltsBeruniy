# Our Mock: ustoz qo'shadigan testlar uchun jadvallar
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0016_add_competition_url'),
    ]

    operations = [
        migrations.CreateModel(
            name='MockPreview',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(db_index=True, max_length=64, unique=True)),
                ('skill', models.CharField(max_length=20)),
                ('payload', models.JSONField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='MockTest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('skill', models.CharField(choices=[('listening', 'Listening'), ('reading', 'Reading')], max_length=20)),
                ('series_id', models.PositiveIntegerField(help_text='Mock raqami')),
                ('test_num', models.PositiveIntegerField(default=1)),
                ('title', models.CharField(blank=True, default='', max_length=200)),
                ('payload', models.JSONField()),
                ('is_published', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_mocks', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['series_id', 'skill'],
            },
        ),
        migrations.AddConstraint(
            model_name='mocktest',
            constraint=models.UniqueConstraint(fields=('skill', 'series_id', 'test_num'), name='unique_mock_skill_series_test'),
        ),
    ]
