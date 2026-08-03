from django.contrib import admin

from .models import News, NewsComment, NewsReaction, NewsRead, TestResult, User


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


@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ['title', 'is_published', 'published_at']
    list_filter = ['is_published']


@admin.register(NewsComment)
class NewsCommentAdmin(admin.ModelAdmin):
    list_display = ['news', 'user', 'text', 'created_at']


@admin.register(NewsReaction)
class NewsReactionAdmin(admin.ModelAdmin):
    list_display = ['news', 'user', 'reaction']


@admin.register(NewsRead)
class NewsReadAdmin(admin.ModelAdmin):
    list_display = ['news', 'user', 'viewed_at']
