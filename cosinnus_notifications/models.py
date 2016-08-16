# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models
from django.db.models import Q
from django.utils.translation import ugettext_lazy as _, pgettext_lazy as p_
from django.utils.encoding import python_2_unicode_compatible

from cosinnus.conf import settings

@python_2_unicode_compatible
class UserNotificationPreference(models.Model):
    
    # do not send notifications for this event
    SETTING_NEVER = 0
    # send the notification immediately
    SETTING_NOW = 1
    # aggregate this notification for a daily email
    SETTING_DAILY = 2
    # aggregate this email for a weekly email
    SETTING_WEEKLY = 3
    
    SETTING_CHOICES = (
        (SETTING_NEVER, p_('notification frequency', 'Never')),
        (SETTING_NOW, p_('notification frequency', 'Immediately')),
        (SETTING_DAILY, p_('notification frequency', 'Daily')),
        (SETTING_WEEKLY, p_('notification frequency', 'Weekly')),
    )
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
        verbose_name=_('Notification Preference for User'),
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    group = models.ForeignKey(settings.COSINNUS_GROUP_OBJECT_MODEL, related_name='user_notification_preferences',
        on_delete=models.CASCADE)
    notification_id = models.CharField(_('Notification ID'), max_length=100)
    
    setting = models.PositiveSmallIntegerField(choices=SETTING_CHOICES,
            db_index=True, default=SETTING_NOW,
            help_text='Determines if the mail for this notification should be sent out at all, immediately, or aggregated (if so, every how often)')
    
    date = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        app_label = 'cosinnus_notifications'
        unique_together = (('user', 'notification_id', 'group'),)
        verbose_name = _('Notification Preference')
        verbose_name_plural = _('Notification Preferences')

    def __str__(self):
        return "<User notification preference: %(user)s, group: %(group)s, notification_id: %(notification_id)s, setting: %(setting)d>" % {
            'user': self.user,
            'notification_id': self.notification_id,
            'setting': self.setting,
            'group': self.group,
        }


import django
if django.VERSION[:2] < (1, 7):
    from cosinnus_notifications import cosinnus_app
    cosinnus_app.register()
