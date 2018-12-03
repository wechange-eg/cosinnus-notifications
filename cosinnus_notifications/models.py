# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from builtins import str
from builtins import object
from django.db import models
from django.db.models import Q
from django.utils.translation import ugettext_lazy as _, pgettext_lazy
from django.utils.encoding import python_2_unicode_compatible

from cosinnus.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes import generic
from cosinnus.models.group import CosinnusPortal
from annoying.functions import get_object_or_None


class BaseUserNotificationPreference(models.Model):
    
    # do not send notifications for this event
    SETTING_NEVER = 0
    # send the notification immediately
    SETTING_NOW = 1
    # aggregate this notification for a daily email
    SETTING_DAILY = 2
    # aggregate this email for a weekly email
    SETTING_WEEKLY = 3
    
    SETTING_CHOICES = (
        (SETTING_NEVER, pgettext_lazy('notification frequency', 'Never')),
        (SETTING_NOW, pgettext_lazy('notification frequency', 'Immediately')),
        (SETTING_DAILY, pgettext_lazy('notification frequency', 'Daily')),
        (SETTING_WEEKLY, pgettext_lazy('notification frequency', 'Weekly')),
    )
    
    SETTINGS_DAYS_DURATIONS = {
        SETTING_NEVER: 0,
        SETTING_NOW: 0,
        SETTING_DAILY: 1,
        SETTING_WEEKLY: 7,        
    }
    
    setting = models.PositiveSmallIntegerField(choices=SETTING_CHOICES,
            db_index=True, default=SETTING_NOW,
            help_text='Determines if the mail for this notification should be sent out at all, immediately, or aggregated (if so, every how often)')
    
    date = models.DateTimeField(auto_now_add=True, editable=False)
    
    class Meta(object):
        abstract = True
        
    
@python_2_unicode_compatible
class UserNotificationPreference(BaseUserNotificationPreference):
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
        verbose_name=_('Notification Preference for User'),
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    group = models.ForeignKey(settings.COSINNUS_GROUP_OBJECT_MODEL, related_name='user_notification_preferences',
        on_delete=models.CASCADE)
    notification_id = models.CharField(_('Notification ID'), max_length=100)
    
    class Meta(object):
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


@python_2_unicode_compatible
class UserMultiNotificationPreference(BaseUserNotificationPreference):
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
        verbose_name=_('Notification Preference for User'),
        on_delete=models.CASCADE,
        related_name='multi_notifications'
    )
    portal = models.ForeignKey('cosinnus.CosinnusPortal', verbose_name=_('Portal'), related_name='user_multi_notifications', 
        null=False, blank=False, default=1)
    multi_notification_id = models.CharField(_('Multi Notification ID'), max_length=100)
    
    class Meta(object):
        app_label = 'cosinnus_notifications'
        unique_together = (('user', 'multi_notification_id',),)
        verbose_name = _('Multi Notification Preference')
        verbose_name_plural = _('Multi Notification Preferences')

    def __str__(self):
        return "<User multi notification preference: %(user)s, multi_notification_id: %(multi_notification_id)s, setting: %(setting)d>" % {
            'user': self.user,
            'notification_id': self.notification_id,
            'setting': self.setting,
        }
        
    @classmethod
    def get_setting_for_user(cls, user, multi_notification_id, portal=None):
        """ Gets the setting for a multi-preference set for a user, or the default value
            TODO: cache!
        """
        if portal is None:
            portal = CosinnusPortal.get_current()
        multi_pref = get_object_or_None(cls, user=user, multi_notification_id=multi_notification_id, portal=CosinnusPortal.get_current())
        if multi_pref is not None:
            return multi_pref.setting
        else:
            from cosinnus_notifications.notifications import MULTI_NOTIFICATION_IDS
            return MULTI_NOTIFICATION_IDS[multi_notification_id]


@python_2_unicode_compatible
class NotificationEvent(models.Model):
    
    class Meta(object):
        ordering = ('date',)
        
    content_type = models.ForeignKey(ContentType)
    object_id = models.PositiveIntegerField()
    target_object = generic.GenericForeignKey('content_type', 'object_id')
    
    group = models.ForeignKey(settings.COSINNUS_GROUP_OBJECT_MODEL, related_name='notifcation_events',
        on_delete=models.CASCADE, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
        verbose_name=_('User who caused this notification event'),
        on_delete=models.CASCADE,
        related_name='+'
    )
    notification_id = models.CharField(_('Notification ID'), max_length=100)
    audience = models.TextField(verbose_name=_('Audience'), blank=False,
        help_text='This is a pseudo comma-seperated integer field, which always starts and ends with a comma for faster queries')
    
    date = models.DateTimeField(auto_now_add=True, editable=False)
    
    def __str__(self):
        return "<NotificationEvent: %(user)s, group: %(group)s, notification_id: %(notification_id)s, date: %(date)s>" % {
            'user': self.user,
            'notification_id': self.notification_id,
            'date': str(self.date),
            'group': self.group,
        }

import django
if django.VERSION[:2] < (1, 7):
    from cosinnus_notifications import cosinnus_app
    cosinnus_app.register()
