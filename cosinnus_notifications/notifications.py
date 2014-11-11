# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from collections import defaultdict

from cosinnus.core.registries.apps import app_registry
from django.utils.importlib import import_module
from cosinnus.core.mail import get_common_mail_context, send_mail_or_fail
from django.template.loader import render_to_string
from cosinnus.utils.functions import ensure_dict_keys


# the dict to store all configured notification signals and options
notifications = {}

def _find_notification(signal):
    """ Finds a configured notification for a received signal """
    for signal_id, options in notifications.items():
        if signal in options['signals']:
            return signal_id
    return None

def check_user_wants_notification(user, notification_id):
    ">>> dummy notification WANT check: returning True"
    return True

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
        if check_user_wants_notification(receiver, notification_id):
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
                signal_id = "%s:%s" % (app_name, signal_id)
                ensure_dict_keys(options, ['label', 'mail_template', 'subject_template', 'signals'], \
                    "The configured notification '%s' of app '%s' was missing the following dict keys: %%s" \
                    % (signal_id, app_name))
                
                options['app_name'] = app_name
                print "connecting", signal_id
                notifications[signal_id] = options
                # connect to signals
                for signal in options['signals']:
                    signal.connect(notification_receiver)
                
            