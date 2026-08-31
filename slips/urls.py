from django.urls import path

from . import views

app_name = 'slips'

urlpatterns = [
    path('api/student/', views.student_lookup_json, name='student_lookup'),
    path('', views.slip_list, name='list'),
    path('create/', views.slip_create, name='create'),
    path('create/release/', views.slip_create_for_release, name='create_release'),
    path('from-assignment/<int:pk>/', views.slip_create_from_assignment, name='from_assignment'),
    path('<int:pk>/', views.slip_detail, name='detail'),
    path('<int:pk>/edit/', views.slip_edit, name='edit'),
    path('<int:pk>/print/', views.slip_print, name='print'),
    path('<int:pk>/delete/', views.slip_delete, name='delete'),
]
