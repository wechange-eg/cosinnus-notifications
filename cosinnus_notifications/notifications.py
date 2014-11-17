# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from collections import defaultdict

from django.template.loader import render_to_string
from django.utils.translation import ugettext_lazy as _
from django.utils.importlib import import_module

from cosinnus.core.mail import get_common_mail_context, send_mail_or_fail
from cosinnus.core.registries.apps import app_registry
from cosinnus.models.group import CosinnusGroup
from cosinnus.models.tagged import BaseTaggableObjectModel
from cosinnus_notifications.models import UserNotificationPreference
from cosinnus.utils.functions import ensure_dict_keys

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

def is_notification_active(notification_id, user, group):
    """ Checks against the DB if a user notifcation preference exists, and if so, if it is set to active """
    try:
        preference = UserNotificationPreference.objects.get(user=user, group=group, notification_id=notification_id)
    except UserNotificationPreference.DoesNotExist:
        print ">> checked notification preference", notification_id, " for", user, group, " and it is >>> false (noexist)"
        # if not set in DB, check if preference is default on 
        if notification_id in notifications and notifications[notification_id].get('default', False):
            print ">> checked notification preference", notification_id, " for", user, group, " and it is >>> true (default)"
            return True
        return False
    print ">> checked notification preference", notification_id, " for", user, group, " and it is >>> ", preference.is_active
    return preference.is_active

def set_user_group_notifications_special(user, group, all_or_none_or_custom):
    """ Sets the user preference settings for a group to all or none or custom (deleting the special setting flag) """
    if not (all_or_none_or_custom == "all" or all_or_none_or_custom == "none" or all_or_none_or_custom == "custom"):
        print ">> Imporperly sent all/none setting to DB"
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
        
        
def check_user_wants_notification(user, notification_id, obj):
    """ Do multiple pre-checks and a DB check to find if the user wants to receive a mail for a 
        notification event. """
    user_in_group = None
    group = None
    if type(obj) is CosinnusGroup or issubclass(obj.__class__, CosinnusGroup):
        group = obj
        user_in_group = group.is_member(user)
    elif issubclass(obj.__class__, BaseTaggableObjectModel):
        group = obj.group
        user_in_group = group.is_member(user)
        
    print ">> checking if user wants notification ", notification_id, "(is he in the group/object's group?)", user_in_group
    if not user_in_group:
        print ">>> user didn't want notification or there was no group"
        return False
    if is_notification_active(NO_NOTIFICATIONS_ID, user, group):
        print ">>> user didn't want notification because he wants none ever!"
        return False
    if is_notification_active(ALL_NOTIFICATIONS_ID, user, group):
        print ">>> user wants notification because he wants all!"
        return True
    ret = is_notification_active(notification_id, user, group)
    print ">> checked his settings, and user wants this notification is", ret
    return ret

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
    
    print ">>> notify caught a signal with id", notification_id, "and audience", audience
    for receiver in audience:
        if check_user_wants_notification(receiver, notification_id, obj):
            template = options['mail_template']
            subj_template = options['subject_template']
            if sender.request:
                context = get_common_mail_context(sender.request)
            else:
                print ">>> warn: no request in sender"
                context = {}
            
            context.update({
                'receiver': receiver,
                'source_user': user,
                'object': obj,
            })
            subject = render_to_string(subj_template, context)
            send_mail_or_fail(receiver.email, subject, template, context)


def init_notifications():
    global notifications 
    
    print ">> init notifications"
    for app, app_name, app_label in app_registry.items():
        print "initing notifics for ", app, app_name, app_label
        try:
            notification_module = import_module('%s.cosinnus_notifications' % app)
        except ImportError:
            continue
        if hasattr(notification_module, 'notifications'):
            print ">> sigs:", notification_module.notifications
            for signal_id, options in notification_module.notifications.items():
                #label, template, signals
                signal_id = "%s__%s" % (app_name, signal_id)
                ensure_dict_keys(options, ['label', 'mail_template', 'subject_template', 'signals'], \
                    "The configured notification '%s' of app '%s' was missing the following dict keys: %%s" \
                    % (signal_id, app_name))
                
                options['app_name'] = app_name
                if not 'default' in options:
                    options['default'] = False
                print "connecting", signal_id
                notifications[signal_id] = options
                # connect to signals
                for signal in options['signals']:
                    signal.connect(notification_receiver)
                

