# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import logging

from django.core.exceptions import ImproperlyConfigured
from django.core.urlresolvers import reverse
from django.utils.translation import ugettext_lazy as _
from django.utils.importlib import import_module
from django.template.loader import render_to_string

from cosinnus.core.mail import get_common_mail_context, send_mail_or_fail
from cosinnus.core.registries.apps import app_registry
from cosinnus.models.group import CosinnusGroup
from cosinnus.models.tagged import BaseTaggableObjectModel
from cosinnus_notifications.models import UserNotificationPreference
from cosinnus.templatetags.cosinnus_tags import full_name, cosinnus_setting
from cosinnus.utils.functions import ensure_dict_keys
from threading import Thread
from django.utils.safestring import mark_safe
from django.utils.html import strip_tags


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



def _find_notification(signal):
    """ Finds a configured notification for a received signal """
    for signal_id, options in notifications.items():
        if signal in options['signals']:
            return signal_id
    return None


def set_user_group_notifications_special(user, group, all_or_none_or_custom):
    """ Sets the user preference settings for a group to all or none or custom (deleting the special setting flag) """
    if not (all_or_none_or_custom == "all" or all_or_none_or_custom == "none" or all_or_none_or_custom == "custom"):
        return
    
    try:
        al = UserNotificationPreference.objects.get(user=user, group=group, notification_id=ALL_NOTIFICATIONS_ID)
        if all_or_none_or_custom == "all":
            if not al.is_active:
                al.is_active = True
                al.save()
        else:
            al.delete()
    except:
        if all_or_none_or_custom == "all":
            UserNotificationPreference.objects.create(user=user, group=group, notification_id=ALL_NOTIFICATIONS_ID, is_active=True)
    try:
        non = UserNotificationPreference.objects.get(user=user, group=group, notification_id=NO_NOTIFICATIONS_ID)
        if all_or_none_or_custom == "none":
            if not non.is_active:
                non.is_active = True
                non.save()
        else:
            non.delete()
    except:
        if all_or_none_or_custom == "none":
            UserNotificationPreference.objects.create(user=user, group=group, notification_id=NO_NOTIFICATIONS_ID, is_active=True)
        


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
                if not 'default' in options:
                    options['default'] = False
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
    
    def is_notification_active(self, notification_id, user, group):
        """ Checks against the DB if a user notifcation preference exists, and if so, if it is set to active """
        try:
            preference = UserNotificationPreference.objects.get(user=user, group=group, notification_id=notification_id)
        except UserNotificationPreference.DoesNotExist:
            # if not set in DB, check if preference is default on 
            if notification_id in notifications and notifications[notification_id].get('default', False):
                return True
            return False
        return preference.is_active
    
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
        
        group = None
        
        if type(obj) is CosinnusGroup or issubclass(obj.__class__, CosinnusGroup):
            group = obj
        elif issubclass(obj.__class__, BaseTaggableObjectModel):
            group = obj.group
        elif hasattr(obj, 'group'):
            group = obj.group
        else:
            raise ImproperlyConfigured('A signal for a notification was received, but the supplied object\'s group could not be determined. \
                If your object is not a CosinnusGroup or a BaseTaggableObject, you can fix this by patching a ``group`` attribute onto it.')
        user_in_group = group.is_member(user)
        
        # print ">> checking if user wants notification ", notification_id, "(is he in the group/object's group?)", user_in_group
        if not user_in_group:
            # >>> user didn't want notification or there was no group
            return False
        if self.is_notification_active(NO_NOTIFICATIONS_ID, user, group):
            # >>> user didn't want notification because he wants none ever!
            return False
        if self.is_notification_active(ALL_NOTIFICATIONS_ID, user, group):
            # >>> user wants notification because he wants all!
            return True
        ret = self.is_notification_active(notification_id, user, group)
        # >> checked his settings, and user wants this notification is", ret
        return ret


    def run(self):
        from cosinnus.utils.context_processors import cosinnus as cosinnus_context
        
        for receiver in self.audience:
            if self.check_user_wants_notification(receiver, self.notification_id, self.obj):
                template = self.options['mail_template']
                subj_template = self.options['subject_template']
                if self.sender.request:
                    context = get_common_mail_context(self.sender.request)
                    context.update(cosinnus_context(self.sender.request))
                else:
                    context = {} #print ">>> warn: no request in sender"
                context.update({'receiver':receiver, 'receiver_name':mark_safe(strip_tags(full_name(receiver))), 'sender':self.user, 'sender_name':mark_safe(strip_tags(full_name(self.user))), 'object':self.obj, 'notification_settings_url':'%s%s' % (context['domain_url'], reverse('cosinnus:notifications'))})
                # additional context for BaseTaggableObjectModels
                if issubclass(self.obj.__class__, BaseTaggableObjectModel):
                    context.update({'object_name': mark_safe(strip_tags(self.obj.title)), 'team_name': mark_safe(strip_tags(self.obj.group.name))})
                else:
                    group = getattr(self.obj, 'group', None)
                    context.update({'team_name': mark_safe(strip_tags(getattr(group, 'name', '<notfound>')))})
                try:
                    context.update({'object_url':self.obj.get_absolute_url()})
                except:
                    print "pass"
                subject = render_to_string(subj_template, context)
                send_mail_or_fail(receiver.email, subject, template, context)
                
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

