from django.urls import path

from . import views

app_name = 'adminpanel'

urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('api/hall-children/', views.hall_children_json, name='hall_children_json'),

    # Halls (only halls)
    path('halls/', views.HallListView.as_view(), name='hall_list'),
    path('halls/add/', views.HallCreateView.as_view(), name='hall_add'),
    path('halls/<int:pk>/edit/', views.HallUpdateView.as_view(), name='hall_edit'),
    path('halls/<int:pk>/delete/', views.HallDeleteView.as_view(), name='hall_delete'),

    # Blocks
    path('blocks/', views.BlockListView.as_view(), name='block_list'),
    path('blocks/add/', views.BlockCreateView.as_view(), name='block_add'),
    path('blocks/<int:pk>/edit/', views.BlockUpdateView.as_view(), name='block_edit'),
    path('blocks/<int:pk>/delete/', views.BlockDeleteView.as_view(), name='block_delete'),

    # Floors
    path('floors/', views.FloorListView.as_view(), name='floor_list'),
    path('floors/add/', views.FloorCreateView.as_view(), name='floor_add'),
    path('floors/<int:pk>/edit/', views.FloorUpdateView.as_view(), name='floor_edit'),
    path('floors/<int:pk>/delete/', views.FloorDeleteView.as_view(), name='floor_delete'),

    # Rooms
    path('rooms/', views.RoomListView.as_view(), name='room_list'),
    path('rooms/add/', views.RoomCreateView.as_view(), name='room_add'),
    path('rooms/<int:pk>/edit/', views.RoomUpdateView.as_view(), name='room_edit'),
    path('rooms/<int:pk>/delete/', views.RoomDeleteView.as_view(), name='room_delete'),

    # Seats
    path('seats/', views.SeatListView.as_view(), name='seat_list'),
    path('seats/add/', views.SeatCreateView.as_view(), name='seat_add'),
    path('seats/<int:pk>/edit/', views.SeatUpdateView.as_view(), name='seat_edit'),
    path('seats/<int:pk>/delete/', views.SeatDeleteView.as_view(), name='seat_delete'),

    # People (Hall Managers / Users)
    path('users/', views.UserListView.as_view(), name='user_list'),
    path('users/add/', views.UserCreateView.as_view(), name='user_add'),
    path('users/<int:pk>/edit/', views.UserUpdateView.as_view(), name='user_edit'),
    path('users/<int:pk>/delete/', views.UserDeleteView.as_view(), name='user_delete'),

    # Students
    path('students/', views.StudentListView.as_view(), name='student_list'),
    path('students/add/', views.StudentCreateView.as_view(), name='student_add'),
    path('students/<int:pk>/edit/', views.StudentUpdateView.as_view(), name='student_edit'),
    path('students/<int:pk>/delete/', views.StudentDeleteView.as_view(), name='student_delete'),
    path('students/pull/', views.StudentPullView.as_view(), name='student_pull'),

    # Allocation calls
    path('allocation-calls/', views.CallListView.as_view(), name='call_list'),

    # Assignments, audit logs, release reasons
    path('assignments/', views.AssignmentListView.as_view(), name='assignment_list'),
    path('logs/', views.LogListView.as_view(), name='log_list'),
    path('release-reasons/', views.ReasonListView.as_view(), name='reason_list'),
    path('release-reasons/add/', views.ReasonCreateView.as_view(), name='reason_add'),
    path('release-reasons/<int:pk>/edit/', views.ReasonUpdateView.as_view(), name='reason_edit'),
    path('release-reasons/<int:pk>/delete/', views.ReasonDeleteView.as_view(), name='reason_delete'),
]
