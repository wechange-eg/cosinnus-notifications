# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import logging

from django.core.exceptions import ImproperlyConfigured
from django.core.urlresolvers import reverse
from django.utils import translation
from django.utils.translation import ugettext_lazy as _
from django.utils.importlib import import_module
from django.template.loader import render_to_string

from cosinnus.conf import settings
from cosinnus.core.mail import get_common_mail_context, send_mail_or_fail
from cosinnus.core.registries.apps import app_registry
from cosinnus.models.group import CosinnusGroup
from cosinnus.models.tagged import BaseTaggableObjectModel, BaseTagObject
from cosinnus_notifications.models import UserNotificationPreference,\
    NotificationEvent
from cosinnus.templatetags.cosinnus_tags import full_name, cosinnus_setting
from cosinnus.utils.functions import ensure_dict_keys
from threading import Thread
from django.utils.safestring import mark_safe
from django.utils.html import strip_tags
from django.contrib.contenttypes.models import ContentType
from cosinnus.utils.permissions import check_object_read_access


logger = logging.getLogger('cosinnus')

ALL_NOTIFICATIONS_ID = 'notifications__all'
NO_NOTIFICATIONS_ID = 'notifications__none'

# the dict to store all configured notification signals and options
# notification settings from all cosinnus apps are added to this one
notifications = {
    ALL_NOTIFICATIONS_ID: {
        'label': _('All notifications'), # special, hardcoded notification preference has no further settings
        'mail_template': '',
        'subject_template': '',
        'signals': [],
    },  
    NO_NOTIFICATIONS_ID: {
        'label': _('No notifications'), # special, hardcoded notification preference has no further settings
        'mail_template': '',
        'subject_template': '',
        'signals': [], 
    },  
}

NOTIFICATION_REASONS = {
    'default': _('You are getting this notification because you are subscribed to these kinds of events in your project or group.'),
    'admin': _('You are getting this notification because you are an administrator of this project or group.'),
    'portal_admin': _('You are getting this notification because you are an administrator of this portal.'),
    'daily_digest': _('You are getting this email because you are subscribed to one or more daily notifications.'),
    'weekly_digest': _('You are getting this email because you are subscribed to one or more weekly notifications.'),
}

REQUIRED_NOTIFICATION_ATTRIBUTE = object()
REQUIRED_NOTIFICATION_ATTRIBUTE_FOR_HTML = object()


# this is a lookup for all defaults of a notification definition
NOTIFICATIONS_DEFAULTS = {
    # Label for the notification option in user's preference
    'label': REQUIRED_NOTIFICATION_ATTRIBUTE, 
    # text-only mail body template. ignored for HTML mails
    'mail_template': REQUIRED_NOTIFICATION_ATTRIBUTE,
    # text-only mail subject template. ignored for HTML mails
    'subject_template': REQUIRED_NOTIFICATION_ATTRIBUTE,
    # a django signal on which to listen for
    'signals': [REQUIRED_NOTIFICATION_ATTRIBUTE],
    # should this notification preference be on by default (if the user has never changed the setting?)
    'default': False,
    
    # does this notification support HTML emails and digest chunking?
    'is_html': False,
    # the snippet template for this notification's event (only used in digest emails, not instant ones)
    'snippet_template': 'cosinnus/html_mail/summary_item.html',
    # CSS class of the snippet template that customizes this notification by its type. usually the cosinnus app's name
    'snippet_type': 'news',
    # the HTML email's subject. use a gettext_lazy translatable string.
    # available variables: %(sender_name)s, %(team_name)s
    'subject_text': REQUIRED_NOTIFICATION_ATTRIBUTE_FOR_HTML,
    # little explanatory text of what happened here. (e.g. "new document", "upcoming event") 
    'event_text': _('New item'),
    # Little text on the bottom of the mail explaining why the user received it. (only in instant mails)
    # see notifications.NOTIFICATION_REASONS
    'notification_reason': 'default', 
    # object attributes to fille the snippet template with. 
    # these will be looked up on the object as attribute or functions with no params
    'data_attributes': {
        'object_name': 'title', # Main title and label of the notification object
        'object_url': 'get_absolute_url', # URL of the object
        'object_text': None, # further excerpt text of the object, for example for Event descriptions. if None: ignored
        'image_url': None, # image URL for the item. if None, uses avatar of the notification causing user
        'event_meta': None, # a small addendum to the grey event text where object data like datetimes can be displayed
        'sub_event_text': None,
        'sub_event_meta': None,
        'sub_image_url': None,
        'sub_object_text': None,
    },
}


def _find_notification(signal):
    """ Finds a configured notification for a received signal """
    for signal_id, options in notifications.items():
        if signal in options['signals']:
            return signal_id
    return None


def set_user_group_notifications_special(user, group, all_or_none_or_custom):
    """ Sets the user preference settings for a group to all or none or custom (deleting the special setting flag) """
    if not (all_or_none_or_custom.startswith("all_") or all_or_none_or_custom in ("none", "custom")):
        return
    
    try:
        al = UserNotificationPreference.objects.get(user=user, group=group, notification_id=ALL_NOTIFICATIONS_ID)
        if all_or_none_or_custom.startswith("all_"):
            setting_value = int(all_or_none_or_custom.split("_")[1])
            if setting_value in dict(UserNotificationPreference.SETTING_CHOICES).keys() and al.setting != setting_value:
                al.setting = setting_value
                al.save()
        else:
            al.delete()
    except:
        if all_or_none_or_custom.startswith("all_"):
            setting_value = int(all_or_none_or_custom.split("_")[1])
            if not setting_value in dict(UserNotificationPreference.SETTING_CHOICES).keys():
                setting_value = UserNotificationPreference.SETTING_NOW
            UserNotificationPreference.objects.create(user=user, group=group, notification_id=ALL_NOTIFICATIONS_ID, setting=setting_value)
    try:
        non = UserNotificationPreference.objects.get(user=user, group=group, notification_id=NO_NOTIFICATIONS_ID)
        if all_or_none_or_custom == "none":
            if not non.setting == UserNotificationPreference.SETTING_NOW:
                non.setting = UserNotificationPreference.SETTING_NOW
                non.save()
        else:
            non.delete()
    except:
        if all_or_none_or_custom == "none":
            UserNotificationPreference.objects.create(user=user, group=group, notification_id=NO_NOTIFICATIONS_ID, setting=UserNotificationPreference.SETTING_NOW)
        


def init_notifications():
    global notifications 
    
    all_items = [item for item in app_registry.items()]
    all_items.append( ('cosinnus', 'cosinnus', '') )
    for app, app_name, app_label in all_items:
        try:
            notification_module = import_module('%s.cosinnus_notifications' % app)
        except ImportError:
            continue
        if hasattr(notification_module, 'notifications'):
            for signal_id, options in notification_module.notifications.items():
                #label, template, signals
                signal_id = "%s__%s" % (app_name, signal_id)
                ensure_dict_keys(options, ['label', 'mail_template', 'subject_template', 'signals'], \
                    "The configured notification '%s' of app '%s' was missing the following dict keys: %%s" \
                    % (signal_id, app_name))
                
                options['app_name'] = app_name
                options['app_label'] = app_label
                # add missing notification settings
                for key, default in NOTIFICATIONS_DEFAULTS.items():
                    if options.get(key, None) is None:
                        if default == REQUIRED_NOTIFICATION_ATTRIBUTE or \
                                (options.get('is_html', False) and default == REQUIRED_NOTIFICATION_ATTRIBUTE_FOR_HTML):
                            raise ImproperlyConfigured('Notification options key "%s" in notification signal "%s" is required!' % (key, signal_id))
                        options[key] = default
                for datakey, datadefault in NOTIFICATIONS_DEFAULTS['data_attributes'].items():
                    if options['data_attributes'].get(datakey, None) is None:
                        options['data_attributes'][datakey] = datadefault
                    
                notifications[signal_id] = options
                # connect to signals
                for signal in options['signals']:
                    signal.connect(notification_receiver)
    logger.info('Cosinnus_notifications: init complete. Available notification signals: %s' % notifications.keys())


class NotificationsThread(Thread):

    def __init__(self, sender, user, obj, audience, notification_id, options):
        super(NotificationsThread, self).__init__()
        self.sender = sender
        self.user = user
        self.obj = obj
        self.audience = audience
        self.notification_id = notification_id
        self.options = options
        # this will be set if a notification is sent out to a user, 
        # so we know which preference was responsible and can link to it
        self.notification_preference_triggered = None
        # will be set at runtime
        self.group = None
    
    def is_notification_active(self, notification_id, user, group, alternate_settings_compare=[]):
        """ Checks against the DB if a user notifcation preference exists, and if so, if it is set to active """
        try:
            preference = UserNotificationPreference.objects.get(user=user, group=group, notification_id=notification_id)
            self.notification_preference_triggered = preference
            if len(alternate_settings_compare) == 0:
                return preference.setting == UserNotificationPreference.SETTING_NOW
            else:
                return preference.setting in alternate_settings_compare
        except UserNotificationPreference.DoesNotExist:
            # if not set in DB, check if preference is default on 
            if notification_id in notifications and notifications[notification_id].get('default', False):
                return True
        return False
        
    
    def check_user_wants_notification(self, user, notification_id, obj):
        """ Do multiple pre-checks and a DB check to find if the user wants to receive a mail for a 
            notification event. """
            
        # only active users that have logged in before accepted the TOS get notifications
        if not user.is_active:
            return False
        if not user.last_login:
            return False
        if not cosinnus_setting(user, 'tos_accepted'):
            return False
        # user cannot be object's creator and must be able to read it
        if hasattr(obj, 'creator') and obj.creator == user:
            return False
        if not check_object_read_access(obj, user):
            return False

        if self.is_notification_active(NO_NOTIFICATIONS_ID, user, self.group):
            # user didn't want notification because he wants none ever!
            return False
        elif self.is_notification_active(ALL_NOTIFICATIONS_ID, user, self.group):
            # user wants notification because he wants all!
            return True
        elif self.is_notification_active(ALL_NOTIFICATIONS_ID, user, self.group, 
                     alternate_settings_compare=[UserNotificationPreference.SETTING_DAILY, UserNotificationPreference.SETTING_WEEKLY]):
            # user wants all notifications, but daily/weekly!
            """ TODO: stub for daily/weekly trigger (all notifications) """
            return False
        elif self.is_notification_active(notification_id, user, self.group, 
                     alternate_settings_compare=[UserNotificationPreference.SETTING_DAILY, UserNotificationPreference.SETTING_WEEKLY]):
            """ TODO: stub for daily/weekly trigger (single notification) """
            return False
        else:
            ret = self.is_notification_active(notification_id, user, self.group)
        # checked his settings, and user wants this notification is", ret
        return ret


    def run(self):
        from cosinnus.utils.context_processors import cosinnus as cosinnus_context
        
        # set group, inferred from object
        if type(self.obj) is CosinnusGroup or issubclass(self.obj.__class__, CosinnusGroup):
            self.group = self.obj
        elif issubclass(self.obj.__class__, BaseTaggableObjectModel):
            self.group = self.obj.group
        elif hasattr(self.obj, 'group'):
            self.group = self.obj.group
        else:
            raise ImproperlyConfigured('A signal for a notification was received, but the supplied object\'s group could not be determined. \
                If your object is not a CosinnusGroup or a BaseTaggableObject, you can fix this by patching a ``group`` attribute onto it.')
        
        for receiver in self.audience:
            if self.check_user_wants_notification(receiver, self.notification_id, self.obj):
                
                # switch language to user's preference language
                cur_language = translation.get_language()
                try:
                    translation.activate(getattr(receiver.cosinnus_profile, 'language', settings.LANGUAGES[0][0]))
                    
                    template = self.options['mail_template']
                    subj_template = self.options['subject_template']
                    if self.sender.request:
                        context = get_common_mail_context(self.sender.request)
                        context.update(cosinnus_context(self.sender.request))
                    else:
                        context = {} # no request in sender
                    
                    # if we know the triggering preference, we can link to it directly via ULR anchors
                    url_suffix = ''
                    if self.notification_preference_triggered:
                        group_pk = self.notification_preference_triggered.group_id
                        pref_arg = ''
                        if self.notification_preference_triggered.notification_id not in (NO_NOTIFICATIONS_ID, ALL_NOTIFICATIONS_ID):
                            pref_arg = 'highlight_pref=%d:%s&' % (group_pk, self.notification_preference_triggered.notification_id)
                        url_suffix = '?%shighlight_choice=%d#notif_choice_%d' % (pref_arg, group_pk, group_pk)
                    preference_url = '%s%s%s' % (context['domain_url'], reverse('cosinnus:notifications'), url_suffix)
                    
                    context.update({'receiver':receiver, 'receiver_name':mark_safe(strip_tags(full_name(receiver))), 'sender':self.user, 'sender_name':mark_safe(strip_tags(full_name(self.user))), 'object':self.obj, 'notification_settings_url':mark_safe(preference_url)})
                    
                    # additional context for BaseTaggableObjectModels
                    context.update({'team_name': mark_safe(strip_tags(self.group['name']))})
                    if issubclass(self.obj.__class__, BaseTaggableObjectModel):
                        context.update({'object_name': mark_safe(strip_tags(self.obj.title))})
                    try:
                        context.update({'object_url':self.obj.get_absolute_url()})
                    except:
                        pass
                    
                    is_html = self.options.get('is_html', False)
                    subject = render_to_string(subj_template, context)
                    send_mail_or_fail(receiver.email, subject, template, context, is_html=is_html)
                    
                finally:
                    translation.activate(cur_language)
        
        if self.audience:
            # create a new NotificationEvent that saves this event for digest re-generation
            content_type = ContentType.objects.get_for_model(self.obj.__class__)
            notifevent = NotificationEvent.objects.create(
                content_type=content_type,
                object_id=self.obj.id,
                group=self.group,
                user=self.user,
                notification_id=self.notification_id,
                audience=',%s,' % ','.join([str(receiver.id) for receiver in self.audience]),
            )
          
        return
    

def notification_receiver(sender, user, obj, audience, **kwargs):
    """ Generic receiver function for all notifications 
        sender: the main object that is being updated / created
        user: the user that modified the object and caused the event
        audience: a list of users that are potential targets for the event 
    """
    signal = kwargs['signal']
    # find out configured signal id for the signal we received
    notification_id = _find_notification(signal)
    if not notification_id:
        return
    options = notifications[notification_id]
    
    # update / overwrite options with extra kwargs sent by the signalling code piece individually
    if 'extra' in kwargs: 
        # deepcopy does not work here, so create a new dict
        copy_options = {}
        copy_options.update(options)
        copy_options.update(kwargs['extra'])
        options = copy_options
    
    # sanity check: only send to active users that have an email set
    audience = [aud_user for aud_user in audience if aud_user.is_active and aud_user.email]
    
    notification_thread = NotificationsThread(sender, user, obj, audience, notification_id, options)
    notification_thread.start()

