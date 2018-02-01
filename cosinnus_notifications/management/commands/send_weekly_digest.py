# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import logging
import traceback

from django.core.management.base import BaseCommand, CommandError
from cosinnus_notifications.digest import send_digest_for_current_portal
from cosinnus_notifications.models import UserNotificationPreference
from cosinnus.core.middleware.cosinnus_middleware import initialize_cosinnus_after_startup
from django.utils.encoding import force_text

logger = logging.getLogger('cosinnus')


class Command(BaseCommand):
    help = 'Closes the specified poll for voting'

    def handle(self, *args, **options):
        try:
            initialize_cosinnus_after_startup()
            send_digest_for_current_portal(UserNotificationPreference.SETTING_WEEKLY)
        except Exception, e:
            logger.error('An critical error occured during weekly digest generation and bubbled up completely! Exception was: %s' % force_text(e),
                         extra={'exception': e, 'trace': traceback.format_exc()})
                                