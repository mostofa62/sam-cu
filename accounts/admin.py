from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from hsm.admin_site import hsm_admin_site

from .forms import UserChangeForm, UserCreationForm
from .models import User


@admin.register(User, site=hsm_admin_site)
class UserAdmin(BaseUserAdmin):
    add_form = UserCreationForm
    form = UserChangeForm
    model = User

    list_display = ('full_name', 'email', 'phone', 'is_staff', 'is_active', 'managed_hall')
    list_filter = ('is_staff', 'is_active', 'is_superuser')
    search_fields = ('email', 'phone', 'full_name')
    ordering = ('-date_joined',)
    filter_horizontal = ('groups', 'user_permissions')

    fieldsets = (
        (None, {'fields': ('email', 'phone', 'password')}),
        ('Personal info', {'fields': ('full_name',)}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'groups', 'user_permissions')}),
        ('Hall access', {'fields': ('managed_hall',),
                         'description': 'The single hall this user manages. A hall can have many managers, '
                                        'but a user manages at most one hall. Superusers always access every hall.'}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('full_name', 'email', 'phone', 'password1', 'password2', 'is_staff', 'groups',
                       'managed_hall'),
        }),
    )
