from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    """Manager for custom User model without username field."""

    use_in_migrations = True

    def _create_user(self, email, phone, password, **extra_fields):
        if not email and not phone:
            raise ValueError('An email or phone number is required.')
        if email:
            email = self.normalize_email(email)
        user = self.model(email=email, phone=phone, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email=None, phone=None, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, phone, password, **extra_fields)

    def create_superuser(self, email=None, phone=None, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self._create_user(email, phone, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Custom user: login by email OR phone, no username field."""

    phone_regex = RegexValidator(
        regex=r'^\+?1?\d{9,15}$',
        message="Phone number must be entered in the format: '+8801XXXXXXXXX'. Up to 15 digits allowed.",
    )

    full_name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(unique=True, null=True, blank=True)
    phone = models.CharField(validators=[phone_regex], max_length=17, unique=True, null=True, blank=True)

    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)

    managed_hall = models.ForeignKey(
        'halls.Hall', on_delete=models.SET_NULL, null=True, blank=True, related_name='managers',
        help_text='The single hall this user manages (a hall may have many managers). '
                  'Superusers always see every hall.',
    )

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['phone']

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['-date_joined']

    def __str__(self):
        if self.full_name:
            return self.full_name
        return self.email or self.phone or f'User #{self.pk}'

    @property
    def is_hall_manager(self):
        return self.managed_hall_id is not None

    def visible_halls(self):
        """Halls the user can see/act on. Superusers get every hall, everyone else only their own managed hall."""
        from halls.models import Hall
        if self.is_superuser:
            return Hall.objects.all()
        if self.managed_hall_id is None:
            return Hall.objects.none()
        return Hall.objects.filter(pk=self.managed_hall_id)
