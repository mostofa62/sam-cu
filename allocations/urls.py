from django.urls import path

from .views import (active_assignments, allotments, assign, delete_allotments,
                     import_allocations_view, maintenance_list, maintenance_put,
                     maintenance_reason_add, maintenance_reason_edit,
                     maintenance_reason_list, maintenance_remove, release_reason_add,
                     release_reason_edit, release_reason_list,
                     resolve_request_approve, resolve_request_create,
                     resolve_request_detail, resolve_request_list,
                     resolve_request_reject, revoke, revoke_assignment,
                     room_seats_json, rooms_json)

app_name = 'allocations'

urlpatterns = [
    path('assign/', assign, name='assign'),
    path('revoke/', revoke, name='revoke'),
    path('assignments/', active_assignments, name='active_assignments'),
    path('assignments/<int:pk>/revoke/', revoke_assignment, name='revoke_assignment'),
    path('maintenance/', maintenance_list, name='maintenance_list'),
    path('maintenance/put/', maintenance_put, name='maintenance_put'),
    path('maintenance/<int:pk>/remove/', maintenance_remove, name='maintenance_remove'),
    path('maintenance/reasons/', maintenance_reason_list, name='maintenance_reason_list'),
    path('maintenance/reasons/add/', maintenance_reason_add, name='maintenance_reason_add'),
    path('maintenance/reasons/<int:pk>/edit/', maintenance_reason_edit, name='maintenance_reason_edit'),
    path('release-reasons/', release_reason_list, name='release_reason_list'),
    path('release-reasons/add/', release_reason_add, name='release_reason_add'),
    path('release-reasons/<int:pk>/edit/', release_reason_edit, name='release_reason_edit'),
    path('allotments/', allotments, name='allotments'),
    path('allotments/delete/', delete_allotments, name='delete_allotments'),
    path('import/', import_allocations_view, name='import'),
    path('resolve/', resolve_request_list, name='resolve_list'),
    path('resolve/<int:pk>/', resolve_request_detail, name='resolve_detail'),
    path('resolve/<int:pk>/approve/', resolve_request_approve, name='resolve_approve'),
    path('resolve/<int:pk>/reject/', resolve_request_reject, name='resolve_reject'),
    path('resolve/request/<int:pk>/', resolve_request_create, name='resolve_create'),
    path('rooms-json/', rooms_json, name='rooms_json'),
    path('room-seats.json', room_seats_json, name='room_seats_json'),
]
