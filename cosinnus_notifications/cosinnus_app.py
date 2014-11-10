# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from cosinnus.core.signals import all_cosinnus_apps_loaded
from django.dispatch.dispatcher import receiver
from cosinnus_notifications.notifications import init_notifications


def register():
    # Import here to prevent import side effects
    from django.utils.translation import ugettext_lazy as _
    from django.utils.translation import pgettext_lazy
    
    from cosinnus.core.registries import (app_registry, url_registry)

    app_registry.register('cosinnus_notifications', 'notifications', _('Notifications'))
    url_registry.register_urlconf('cosinnus_notifications', 'cosinnus_notifications.urls')

    # makemessages replacement protection
    name = pgettext_lazy("the_app", "notifications")
    
import django.dispatch as dispatch
    
@receiver(all_cosinnus_apps_loaded)
def cosinnus_ready(sender, **kwargs):
    print ">> loadsdaed"
    print ">> ?", bool(kwargs['signal'] == all_cosinnus_apps_loaded), bool(kwargs['signal'] == dispatch.Signal())
    init_notifications()