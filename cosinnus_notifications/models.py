# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import datetime

from django.core.urlresolvers import reverse
from django.db import models as django_models
from django.utils.translation import ugettext_lazy as _
from django.utils.timezone import now

    


import django
if django.VERSION[:2] < (1, 7):
    from cosinnus_notifications import cosinnus_app
    cosinnus_app.register()
