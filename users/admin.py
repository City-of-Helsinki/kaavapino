from django.contrib.auth.admin import UserAdmin
from helusers.admin import admin

from .models import User


@admin.register(User)
class UserAdmin(UserAdmin):
    pass
