# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.contrib import admin
from cosinnus_notifications.models import UserNotificationPreference, NotificationEvent


class UserNotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'group', 'notification_id', 'setting')
    list_filter = ('setting',)
    search_fields = ('user__first_name', 'user__last_name', 'user__email', 'notification_id', 'group__name', 'group__slug') 

admin.site.register(UserNotificationPreference, UserNotificationPreferenceAdmin)


class NotificationEventAdmin(admin.ModelAdmin):
    list_display = ('date', 'notification_id', 'group', 'user')
    list_filter = ('notification_id',)
    search_fields = ('user__first_name', 'user__last_name', 'user__email', 'notification_id', 'group__name') 

admin.site.register(NotificationEvent, NotificationEventAdmin)
