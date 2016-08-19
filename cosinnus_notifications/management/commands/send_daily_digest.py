# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.core.management.base import BaseCommand, CommandError
from cosinnus_notifications.digest import send_digest_for_current_portal
from cosinnus_notifications.models import UserNotificationPreference

class Command(BaseCommand):
    help = 'Closes the specified poll for voting'

    def handle(self, *args, **options):
        send_digest_for_current_portal(UserNotificationPreference.SETTING_DAILY)