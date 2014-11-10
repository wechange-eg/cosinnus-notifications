# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.conf.urls import patterns, url


cosinnus_root_patterns = patterns('',
                                   
)


cosinnus_group_patterns = patterns('cosinnus_stream.views',
)

urlpatterns = cosinnus_group_patterns + cosinnus_root_patterns
