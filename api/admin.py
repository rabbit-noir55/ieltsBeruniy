from django.contrib import admin

from .models import TestResult, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['username', 'first_name', 'last_name', 'role', 'is_staff']
    list_filter = ['role']


@admin.register(TestResult)
class TestResultAdmin(admin.ModelAdmin):
    list_display = [
        'student', 'skill', 'series_id', 'test_num', 'part_num',
        'task_part', 'raw_score', 'band', 'updated_at',
    ]
    list_filter = ['skill', 'series_id']
    search_fields = ['student__username', 'student__first_name', 'student__last_name']
