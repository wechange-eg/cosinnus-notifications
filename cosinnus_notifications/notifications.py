# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from cosinnus.core.registries.apps import app_registry
from django.utils.importlib import import_module


def init_notifications():
    
    print ">> init notifications"
    for app, app_name, app_label in app_registry.items():
        print "initing notifics for ", app, app_name, app_label
        try:
            notification_module = import_module('%s.cosinnus_notifications' % app)
        except ImportError:
            continue
        print ">> sigs:", notification_module.signal_groups