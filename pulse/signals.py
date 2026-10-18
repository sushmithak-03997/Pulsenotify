from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import UserProfile


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Auto-create a UserProfile for every new User.

    Role is never taken from a request: it is USER by default, and only
    superusers (createsuperuser) start out as ADMIN. Any other user can be
    promoted by editing the role in pgAdmin / Django admin.
    """
    if created:
        role = UserProfile.Role.ADMIN if instance.is_superuser else UserProfile.Role.USER
        UserProfile.objects.create(user=instance, role=role)
