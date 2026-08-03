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
    path('writing/feedback/', views.writing_feedback, name='writing_feedback'),
    path('typing/results/', views.typing_results, name='typing_results'),
    path('typing/leaderboard/', views.typing_leaderboard, name='typing_leaderboard'),
    path('news/', views.news_list, name='news_list'),
    path('news/unread-count/', views.news_unread_count, name='news_unread_count'),
    path('news/mark-all-read/', views.news_mark_all_read, name='news_mark_all_read'),
    path('news/<int:news_id>/', views.news_detail, name='news_detail'),
    path('news/<int:news_id>/react/', views.news_react, name='news_react'),
    path('news/<int:news_id>/comments/', views.news_comments, name='news_comments'),
    path('news/<int:news_id>/comments/<int:comment_id>/',
         views.news_comment_delete, name='news_comment_delete'),
    path('panel/', include(([
        path('', panel_views.dashboard, name='dashboard'),
        path('login/', panel_views.login_view, name='login'),
        path('logout/', panel_views.logout_view, name='logout'),
        path('students/<int:student_id>/', panel_views.student_detail, name='student_detail'),
        path('students/<int:student_id>/block/', panel_views.block_student, name='block_student'),
        path('students/<int:student_id>/unblock/', panel_views.unblock_student, name='unblock_student'),
        path('students/<int:student_id>/set-password/', panel_views.set_student_password, name='set_student_password'),
        path('news/', panel_views.news_list, name='news_list'),
        path('news/add/', panel_views.news_add, name='news_add'),
        path('news/<int:news_id>/edit/', panel_views.news_edit, name='news_edit'),
        path('news/<int:news_id>/delete/', panel_views.news_delete, name='news_delete'),
    ], 'panel'), namespace='panel')),
] + router.urls
