# -*- coding: utf-8 -*-
from __future__ import unicode_literals


def register():
    # Import here to prevent import side effects
    from django.utils.translation import ugettext_lazy as _
    from django.utils.translation import pgettext_lazy
    
    from cosinnus.core.registries import (app_registry,
        attached_object_registry, url_registry, widget_registry)

    app_registry.register('cosinnus_notifications', 'notifications', _('Notifications'))
    #attached_object_registry.register('cosinnus_file.FileEntry',
    #                         'cosinnus_file.utils.renderer.FileEntryRenderer')
    url_registry.register_urlconf('cosinnus_notifications', 'cosinnus_notifications.urls')

    # makemessages replacement protection
    name = pgettext_lazy("the_app", "notifications")