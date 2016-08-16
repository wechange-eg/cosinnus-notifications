# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.contrib import admin
from cosinnus_notifications.models import UserNotificationPreference


class UserNotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'group', 'notification_id', 'setting')
    list_filter = ('group', 'user', 'setting',)

admin.site.register(UserNotificationPreference, UserNotificationPreferenceAdmin)
