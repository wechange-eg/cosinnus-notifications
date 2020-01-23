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
from cosinnus.models.group import CosinnusPortal
from annoying.functions import get_object_or_None
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.postgres.fields.jsonb import JSONField
from cosinnus.templatetags.cosinnus_tags import full_name

import logging
from django.template.defaultfilters import date
logger = logging.getLogger('cosinnus')


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
        null=False, blank=False, default=1, on_delete=models.CASCADE)
    multi_notification_id = models.CharField(_('Multi Notification ID'), max_length=100)
    
    class Meta(object):
        app_label = 'cosinnus_notifications'
        unique_together = (('user', 'multi_notification_id', 'portal',),)
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
        multi_pref = get_object_or_None(cls, user=user, multi_notification_id=multi_notification_id, portal=portal)
        if multi_pref is not None:
            return multi_pref.setting
        else:
            from cosinnus_notifications.notifications import MULTI_NOTIFICATION_IDS
            return MULTI_NOTIFICATION_IDS[multi_notification_id]


@python_2_unicode_compatible
class NotificationEvent(models.Model):
    
    class Meta(object):
        ordering = ('date',)
        
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    target_object = GenericForeignKey('content_type', 'object_id')
    
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


@python_2_unicode_compatible
class NotificationAlert(models.Model):
    """ An instant notification alert for something relevant that happened for a user, shown in the navbar dropdown.
        
        The default alert type `TYPE_SINGLE_ALERT` displays only a single event that caused it. It may morph into
        either of the other types, but from them may not be changed again.
        `TYPE_MULTI_ALERT` is for events happening on a single content object, but with multiple users acting on it.
        `TYPE_BUNDLE_ALERT` is a single alert object bundled for multiple content objects causing events in a short 
            time frame, all by the single same user in the same group.
    """
    
    TYPE_SINGLE_ALERT = 0
    TYPE_MULTI_USER_ALERT = 1
    TYPE_BUNDLE_ALERT = 2 
    ALERT_TYPES= (
        (TYPE_SINGLE_ALERT, 'Single Alert'),
        (TYPE_MULTI_USER_ALERT, 'Multi User Alert'),
        (TYPE_BUNDLE_ALERT, 'Bundled Alert'),
    )
    
    class Meta(object):
        ordering = ('last_event_at',)
        unique_together = ('user', 'item_hash', )
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
        verbose_name=_('Owner of the alert'),
        on_delete=models.CASCADE, related_name='+'
    )
    notification_id = models.CharField(_('Notification ID'), max_length=100)

    portal = models.ForeignKey('cosinnus.CosinnusPortal', verbose_name=_('Portal'), related_name='notification_alerts', 
        null=False, blank=False, default=1, on_delete=models.CASCADE)
    group = models.ForeignKey(settings.COSINNUS_GROUP_OBJECT_MODEL, related_name='notifcation_alerts',
        on_delete=models.CASCADE, blank=True, null=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    target_object = GenericForeignKey('content_type', 'object_id')
    
    last_event_at = models.DateTimeField(auto_now_add=True)
    seen = models.BooleanField(default=False, 
            help_text='Whether the owner has seen this alert. May reset to unseen on new events of multi or bundle alerts.')
    
    action_user = models.ForeignKey(settings.AUTH_USER_MODEL,
        verbose_name=_('Last user who caused this notification event'),
        help_text='For multi-user alerts, this points to the last user who changed anything about this alert.',
        on_delete=models.CASCADE, related_name='+'
    )
    
    type = models.PositiveSmallIntegerField(_('Alert State'), blank=False,
        default=TYPE_SINGLE_ALERT, choices=ALERT_TYPES, editable=False,
        help_text='The type of the Alert. Can only morph from single to multi or from single to bundle!')
    
    target_title = models.CharField(max_length=250, 
            help_text='Cached version of the title of the target object')
    target_url = models.URLField(max_length=250, blank=True, null=True,
            help_text='Target URL the alert points to, usually a cached version of the URL of the target object')
    label = models.TextField(help_text='An untranslated, unwrapped i18n text, to be retranslated at retrieval time')
    icon_or_image_url = models.CharField(max_length=250, blank=True, null=True,
            help_text='Either a URL to an image thumbnail, or a fa-icon string. Distinguished by frontend at display time')
    subtitle = models.CharField(max_length=250, blank=True, null=True,
            help_text='Usually a cached version of the group name, or None')
    subtitle_icon = models.CharField(max_length=250, blank=True, null=True,
            help_text='fa-icon string or None')
    
    item_hash = models.CharField(max_length=250,
            help_text='A unique-per-user pseudo-hash to identify an alert and detect multi-user alerts.'
                        'Consists of `<portal-id>/<group-id>/<item-id>/<notification-id>`')
    bundle_hash = models.CharField(max_length=250,
            help_text='A non-unique hash used to detect very similar events to merge as a bundle.' +\
                        'Consists of `<portal-id>/<group-id>/<item-model>/<action-user-id>/<notification-id>`')
    counter = models.PositiveIntegerField(default=0,
            help_text='A counter for displaying a number in the alert like "Amy and <counter> more liked your post".' +\
                        'Used in multi and bundle alerts.')
    multi_user_list = JSONField(null=True, blank=True,
            help_text='Only filled if type==TYPE_MULTI_USER_ALERT, None else.' +\
            'Contains a list of objects for referenced users [{"user_id", "title" (username), "url", "icon_or_image_url"}, ...]')
    bundle_list = JSONField(null=True, blank=True,
            help_text='Only filled if type==TYPE_BUNDLE_ALERT, None else.' +\
            'Contains a list of objects for referenced content objects [{"obj_id", "title", "url", "icon_or_image_url"}, ...]')
    
    def __str__(self):
        return "<NotificationAlert: %(user)s, group: %(group)s, item_hash: %(item_hash)s, last_event_at: %(last_event_at)s>" % {
            'user': self.user,
            'group': str(self.group),
            'item_hash': self.item_hash,
            'last_event_at': str(self.last_event_at),
        }


class SerializedNotificationAlert(dict):
    
    label = None # combines username and count and item name
    url = None
    user_icon_or_image_url = None
    item_icon_or_image_url = None
    subtitle = None
    subtitle_icon = None
    action_datetime = None
    seen = False
    bundle_items = []  # class `BundleItem`
    
    def __init__(self, alert, action_user=None, action_user_profile=None):
        if not action_user:
            logger.warn('>>>>>>>> No action_user supplied for `SerializedNotificationAlert`, retrieving with singular query!')
            action_user = alert.action_user
        if not action_user_profile:
            logger.warn('>>>>>>>> No action_user_profile supplied for `SerializedNotificationAlert`, retrieving with singular query!')
            action_user_profile = action_user.cosinnus_profile
        username = full_name(action_user) 
        # TODO: correct label var names!
        label_vars = {
            'username': username,
            'count': alert.counter,
        }
        # translate the label using current variables
        self['label'] = _(alert.label) % label_vars
        self['url'] = alert.target_url
        self['item_icon_or_image_url'] = alert.icon_or_image_url
        self['user_icon_or_image_url'] = action_user_profile.get_avatar_thumbnail_url()
        self['subtitle'] = alert.subtitle
        self['subtitle_icon'] = alert.subtitle_icon
        self['action_datetime'] = date(alert.last_event_at, 'c') # moment-compatible datetime string
        self['seen'] = alert.seen
        
        bundle_items = []
        if alert.type == NotificationAlert.TYPE_MULTI_USER_ALERT:
            bundle_items = [BundleItem(obj) for obj in alert.multi_user_list]
        elif alert.type == NotificationAlert.TYPE_BUNDLE_ALERT:
            bundle_items = [BundleItem(obj) for obj in alert.bundle_list]
        self['bundle_items'] = bundle_items


class BundleItem(dict):
    
    title = None
    url = None
    icon_or_image_url = None
    
    def __init__(self, obj):
        self['title'] = obj.get('title', None)
        self['url'] = obj.get('url', None)
        self['icon_or_image_url'] = obj.get('icon_or_image_url', None)
        
            