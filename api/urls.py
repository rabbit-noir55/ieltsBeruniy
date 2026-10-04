from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import panel_views, views

router = DefaultRouter()
router.register('results', views.ResultViewSet, basename='result')

urlpatterns = [
    path('health/', views.health, name='health'),
    path('auth/register/', views.register, name='register'),
    path('auth/login/', views.login, name='login'),
    path('auth/me/', views.me, name='me'),
    path('auth/change-password/', views.change_password, name='change_password'),
    path('auth/google/', views.google_login, name='google_login'),
    path('typing/results/', views.typing_results, name='typing_results'),
    path('typing/leaderboard/', views.typing_leaderboard, name='typing_leaderboard'),
    path('ai/chat/', views.ai_chat, name='ai_chat'),
    path('ai/feedback/', views.writing_feedback, name='writing_feedback'),
    path('ai/speaking/', views.speaking_feedback, name='speaking_feedback'),
    path('groups/', views.group_list, name='group_list'),
    path('groups/<slug:slug>/', views.group_detail_by_slug, name='group_detail'),
    path('panel/', include(([
        path('', panel_views.dashboard, name='dashboard'),
        path('login/', panel_views.login_view, name='login'),
        path('logout/', panel_views.logout_view, name='logout'),
        path('students/<int:student_id>/', panel_views.student_detail, name='student_detail'),
        path('students/<int:student_id>/block/', panel_views.block_student, name='block_student'),
        path('students/<int:student_id>/unblock/', panel_views.unblock_student, name='unblock_student'),
        path('students/<int:student_id>/set-password/', panel_views.set_student_password, name='set_student_password'),
        path('students/<int:student_id>/set-group/', panel_views.set_student_group, name='set_student_group'),
        path('students/<int:student_id>/delete/', panel_views.delete_student, name='delete_student'),
        path('groups/', panel_views.group_list, name='group_list'),
        path('groups/add/', panel_views.group_add, name='group_add'),
        path('groups/<int:group_id>/edit/', panel_views.group_edit, name='group_edit'),
        path('groups/<int:group_id>/delete/', panel_views.group_delete, name='group_delete'),
    ], 'panel'), namespace='panel')),
] + router.urls
