# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.conf.urls import patterns, url


cosinnus_root_patterns = patterns('',
    url(r'^profile/notifications/$', 'cosinnus_notifications.views.notification_preference_view', name='notifications'),
    url(r'^profile/reset_notifications/$', 'cosinnus_notifications.views.notification_reset_view', name='reset-notifications'),           
)


cosinnus_group_patterns = patterns('cosinnus_notifications.views',
)

urlpatterns = cosinnus_group_patterns + cosinnus_root_patterns
