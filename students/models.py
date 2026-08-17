from django.conf import settings
from django.db import models


class Student(models.Model):
    """Student record imported from the external student database."""

    class StudentStatus(models.IntegerChoices):
        ACTIVE = 1, 'Active'
        SUSPENDED = 2, 'Suspended'
        CANCELLED = 3, 'Cancelled'
        GRADUATED = 4, 'Graduated'

    student_id = models.CharField(max_length=10, primary_key=True, help_text='Student ID as the natural key.')

    adm_unit = models.CharField(max_length=2, null=True, blank=True)
    adm_quota = models.CharField(max_length=8, null=True, blank=True)
    adm_roll = models.CharField(max_length=6, null=True, blank=True)
    hsc_group = models.CharField(max_length=3, null=True, blank=True)
    adm_merit = models.CharField(max_length=5, null=True, blank=True)
    user_id = models.IntegerField(blank=True, null=True)  # This field is a placeholder for the user ID, which may be linked to an actual User model in the future.
    username = models.CharField(max_length=11, null=True, blank=True)
    session = models.CharField(max_length=9, null=True, blank=True)
    entity_id = models.CharField(max_length=5, null=True, blank=True)
    subject_id = models.CharField(max_length=5, null=True, blank=True)
    name_en = models.CharField(max_length=90, null=True, blank=True)
    name_bn = models.CharField(max_length=90, null=True, blank=True)
    gender = models.CharField(max_length=6, null=True, blank=True)
    religion = models.CharField(max_length=15, null=True, blank=True)
    dob = models.CharField(max_length=10, null=True, blank=True)
    dob_ymd = models.CharField(max_length=11, null=True, blank=True)
    bloodgroup = models.CharField(max_length=5, null=True, blank=True)
    nationality = models.CharField(max_length=20, default='Bangladeshi', blank=True)
    nid = models.CharField(max_length=30, null=True, blank=True)
    phone = models.CharField(max_length=14, null=True, blank=True)
    both_address_same = models.IntegerField(default=0)
    perm_addr = models.CharField(max_length=458, null=True, blank=True)
    perm_dist = models.CharField(max_length=50, null=True, blank=True)
    perm_pcode = models.CharField(max_length=50, null=True, blank=True)
    pres_addr = models.CharField(max_length=458, null=True, blank=True)
    pres_dist = models.CharField(max_length=50, null=True, blank=True)
    pres_pcode = models.CharField(max_length=50, null=True, blank=True)
    fname_en = models.CharField(max_length=90, null=True, blank=True)
    fname_bn = models.CharField(max_length=90, null=True, blank=True)
    fnid = models.CharField(max_length=20, null=True, blank=True)
    foccupation = models.CharField(max_length=50, null=True, blank=True)
    fphone = models.CharField(max_length=14, null=True, blank=True)
    mname_en = models.CharField(max_length=90, null=True, blank=True)
    mname_bn = models.CharField(max_length=90, null=True, blank=True)
    mnid = models.CharField(max_length=20, null=True, blank=True)
    mphone = models.CharField(max_length=14, null=True, blank=True)
    rand_hash = models.CharField(max_length=10, null=True, blank=True)
    hall_code = models.CharField(max_length=6, null=True, blank=True)
    student_status = models.PositiveSmallIntegerField(
        choices=StudentStatus.choices, default=StudentStatus.ACTIVE,
        help_text='1 = active, 2 = suspended, 3 = cancelled, 4 = graduated',
    )

    class Meta:
        verbose_name = 'Student'
        verbose_name_plural = 'Students'
        ordering = ['student_id']

    def __str__(self):
        return f'{self.student_id} - {self.name_en or "(no name)"}'