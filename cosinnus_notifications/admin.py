# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.contrib import admin
from cosinnus_notifications.models import UserNotificationPreference, NotificationEvent


class UserNotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'group', 'notification_id', 'setting')
    list_filter = ('group', 'user', 'setting',)

admin.site.register(UserNotificationPreference, UserNotificationPreferenceAdmin)


class NotificationEventAdmin(admin.ModelAdmin):
    list_display = ('date', 'notification_id', 'group', 'user')
    list_filter = ('group', 'notification_id')

admin.site.register(NotificationEvent, NotificationEventAdmin)
