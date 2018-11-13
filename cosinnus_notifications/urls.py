# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.conf.urls import url
from cosinnus_notifications import views

app_name = 'notifications'

cosinnus_root_patterns = [
    url(r'^profile/notifications/$', views.notification_preference_view, name='notifications'),
    url(r'^profile/reset_notifications/$', views.notification_reset_view, name='reset-notifications'),           
]

cosinnus_group_patterns = []


urlpatterns = cosinnus_group_patterns + cosinnus_root_patterns
