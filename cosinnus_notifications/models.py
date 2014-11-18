# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models
from django.db.models import Q
from django.utils.translation import ugettext_lazy as _
from django.utils.encoding import python_2_unicode_compatible

from cosinnus.conf import settings
from cosinnus.models.group import CosinnusGroup

@python_2_unicode_compatible
class UserNotificationPreference(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
        verbose_name=_('Notification Preference'),
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    group = models.ForeignKey(CosinnusGroup, related_name='user_notification_preferences',
        on_delete=models.CASCADE)
    notification_id = models.CharField(_('Notification ID'), max_length=100)
    is_active = models.BooleanField(default=0)
    
    date = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        app_label = 'cosinnus_notifications'
        unique_together = (('user', 'notification_id', 'group'),)
        verbose_name = _('Notification Preference')
        verbose_name_plural = _('Notification Preferences')

    def __str__(self):
        return "<User notification preference: %(user)s, group: %(group)s, notification_id: %(notification_id)s, is_active: %(is_active)d>" % {
            'user': self.user,
            'notification_id': self.notification_id,
            'is_active': self.is_active,
            'group': self.group,
        }


import django
if django.VERSION[:2] < (1, 7):
    from cosinnus_notifications import cosinnus_app
    cosinnus_app.register()
