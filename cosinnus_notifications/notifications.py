# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from collections import defaultdict

from cosinnus.core.registries.apps import app_registry
from django.utils.importlib import import_module
from cosinnus_notifications.mail import send_mail_or_fail


# the dict to store all configured notification signals and options
notification_groups = defaultdict(list)

def _find_notification(signal):
    """ Finds a configured notification for a received signal """
    the_notification = None
    for app, notifications in notification_groups.items():
        for notification in notifications:
            if signal in notification[3]:
                the_notification = notification
                break
    return the_notification

def check_user_wants_notification(user, notification_id):
    ">>> dummy notification WANT check: returning True"
    return True

def notification_receiver(sender, user, audience, **kwargs):
    """ Generic receiver function for all notifications 
        sender: the main object that is being updated / created
        user: the user that modified the object and caused the event
        audience: a list of users that are potential targets for the event 
    """
    signal = kwargs['signal']
    # find out configured signal id for the signal we received
    notification = _find_notification(signal)
    if not notification:
        return
    
    print ">>> notify caught a signal with id", notification[0], "and audience", audience
    for user in audience:
        if check_user_wants_notification(user, notification[0]):
            template = notification[2]
            get_common_mail_context
            send_mail_or_fail(user.email, subject, template, context)


def init_notifications():
    global notification_groups 
    
    print ">> init notifications"
    for app, app_name, app_label in app_registry.items():
        print "initing notifics for ", app, app_name, app_label
        try:
            notification_module = import_module('%s.cosinnus_notifications' % app)
        except ImportError:
            continue
        print ">> sigs:", notification_module.notification_groups
        for signal_id, label, template, signals in notification_module.notification_groups:
            signal_id = "%s:%s" % (app_name, signal_id)
            print "connecting", signal_id
            notification_groups[app_name].append((signal_id, label, template, signals))
            # connect to signals
            for signal in signals:
                signal.connect(notification_receiver)
            
            
            
            
            