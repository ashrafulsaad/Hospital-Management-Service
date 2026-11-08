from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import Role, User

from .models import PatientProfile


@receiver(post_save, sender=User)
def create_patient_profile(sender, instance, created, **kwargs):
    if created and instance.role == Role.PATIENT:
        PatientProfile.objects.get_or_create(user=instance)
