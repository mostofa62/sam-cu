from django.urls import path

from . import views

app_name = 'halls'

urlpatterns = [
    path('blocks/', views.block_list, name='block_list'),
    path('blocks/add/', views.block_add, name='block_add'),
    path('blocks/<int:pk>/edit/', views.block_edit, name='block_edit'),
    path('blocks/<int:pk>/delete/', views.block_delete, name='block_delete'),

    path('floors/', views.floor_list, name='floor_list'),
    path('floors/add/', views.floor_add, name='floor_add'),
    path('floors/<int:pk>/edit/', views.floor_edit, name='floor_edit'),
    path('floors/<int:pk>/delete/', views.floor_delete, name='floor_delete'),

    path('rooms/', views.room_list, name='room_list'),
    path('rooms/add/', views.room_add, name='room_add'),
    path('rooms/<int:pk>/edit/', views.room_edit, name='room_edit'),
    path('rooms/<int:pk>/delete/', views.room_delete, name='room_delete'),

    path('seats/', views.seat_list, name='seat_list'),
    path('seats/add/', views.seat_add, name='seat_add'),
    path('seats/<int:pk>/edit/', views.seat_edit, name='seat_edit'),
    path('seats/<int:pk>/delete/', views.seat_delete, name='seat_delete'),
]
