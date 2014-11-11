# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.contrib import admin
from cosinnus_notifications.models import UserNotificationPreference


class UserNotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'group', 'notification_id', 'is_active')
    list_filter = ('group', 'user', 'is_active',)

admin.site.register(UserNotificationPreference, UserNotificationPreferenceAdmin)
