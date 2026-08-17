from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

User = get_user_model()


class EmailOrPhoneModelBackend(ModelBackend):
    """Authenticate users using either email or phone as the identifier."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        identifier = kwargs.get('identifier') or username or kwargs.get('email') or kwargs.get('phone')
        if not identifier or not password:
            return None

        try:
            user = User.objects.get(Q(email__iexact=identifier) | Q(phone__iexact=identifier))
        except (User.DoesNotExist, User.MultipleObjectsReturned):
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
