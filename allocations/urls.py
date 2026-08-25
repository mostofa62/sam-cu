from django.urls import path

from .views import (active_assignments, allotments, assign, delete_allotments,
                    import_allocations_view, revoke, revoke_assignment,
                    room_seats_json, rooms_json)

app_name = 'allocations'

urlpatterns = [
    path('assign/', assign, name='assign'),
    path('revoke/', revoke, name='revoke'),
    path('assignments/', active_assignments, name='active_assignments'),
    path('assignments/<int:pk>/revoke/', revoke_assignment, name='revoke_assignment'),
    path('allotments/', allotments, name='allotments'),
    path('allotments/delete/', delete_allotments, name='delete_allotments'),
    path('import/', import_allocations_view, name='import'),
    path('rooms-json/', rooms_json, name='rooms_json'),
    path('room-seats.json', room_seats_json, name='room_seats_json'),
]
