# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from cosinnus_notifications.models import NotificationAlert
from datetime import timedelta
import logging

from django.utils.timezone import now
from django.utils.translation import ugettext_lazy as _


logger = logging.getLogger('cosinnus')



ALERT_REASONS = {
    'is_group': None, # -- reason will not be shown. the item is a group and is always shown for invitations etc
    'is_creator': _('You are seeing this alert because you created this content.'),
    'follow_group': _('You are seeing this alert because you are following the item\'s project or group.'),
    'follow_object': _('You are seeing this alert because you are following this item.'),
    'none': None, # -- reason will not be shown
}

def create_user_alert(obj, group, receiver, action_user, notification_id, reason_key=None):
    """ Creates a NotificationAlert for a NotificationEvent to someone who wants it.
        @param group: can be None (for non-group items or groups themselves) 
        @param reason_key: a key of `ALERT_REASONS` or None. """
        
    # create preliminary alert (not persisted yet!)
    alert = NotificationAlert()
    alert.initialize(
        user=receiver,
        target_object=obj,
        group=group,
        action_user=action_user,
        notification_id=notification_id
    )
    # generate some derived data in the alert derived from its object/event
    alert.fill_notification_dependent_data()
    alert.reason_key = reason_key
    
    # Case A: check if the alert should be merged into an existing multi user alert or bundle alert
    # multi user check: the owner is same, datetime < 3d, and the item_hash matches, 
    # AND THE USER ID IS NOT ALREADY IN THE multi_user_list:
    # TODO: optionize the timeframe
    a_moderate_time_ago = now() - timedelta(days=3)
    multi_user_qs = NotificationAlert.objects.filter(
        user=alert.user,
        last_event_at__gte=a_moderate_time_ago,
        item_hash=alert.item_hash)
    multi_user_qs = list(multi_user_qs)
    if len(multi_user_qs) > 1:
        logger.warning('Inconsistency: Trying to match a multi user alert, but had a QS with more than 1 items!',
                       extra={'alert': str(alert)})
    elif len(multi_user_qs) == 1:
        multi_alert = multi_user_qs[0]
        if not any([user_item['user_id'] == alert.user.id for user_item in multi_alert.multi_user_list]):
            # if there was one matching alert with the user not in the multi_user_list, merge the alerts.
            # Otherwise we *drop* the alert. this is case like a user liking/unliking an item multiple times 
            # in a short time span
            merge_new_alert_into_multi_alert(alert, multi_alert)
        return
    
    # Case B: if no matching alerts for multi alerts were found, check if a bundle alert matches:
    # bundle alert check: the owner is same, datetime < 3h, the bundle_hash matches
    # TODO: optionize the timeframe
    a_short_time_ago = now() - timedelta(hours=3)
    bundle_qs = NotificationAlert.objects.filter(
        user=alert.user,
        last_event_at__gte=a_short_time_ago,
        bundle_hash=alert.bundle_hash)
    bundle_qs = list(bundle_qs)
    if len(multi_user_qs) > 1:
        logger.warning('Inconsistency: Trying to match a multi user alert, but had a QS with more than 1 items!',
                       extra={'alert': str(alert)})
    elif len(bundle_qs) == 1:
        merge_new_alert_into_bundle_alert(alert, bundle_qs[0])
        return
    
    # Case C: if the event caused neither a multi user alert or bundle alert, save alert as a new alert
    alert.generate_label()
    alert.save()
    

def merge_new_alert_into_multi_alert(new_alert, multi_alert):
    """ Merges a newly arrived alert into an existing alert as multi alert.
        The existing alert may yet still be a single alert """
    # sanity check, cannot convert bundle alerts
    if multi_alert.type not in (NotificationAlert.TYPE_SINGLE_ALERT, NotificationAlert.TYPE_MULTI_USER_ALERT):
        logger.warning('Inconsistency: Trying to create a multi user alert, but matched existing alert was a bundle alert!',
                       extra={'alert': str(multi_alert)})
        return
    # make the old alert a multi alert, add the new action user and reset it to be current
    if multi_alert.type == NotificationAlert.TYPE_SINGLE_ALERT:
        multi_alert.type = NotificationAlert.TYPE_MULTI_USER_ALERT
        multi_alert.add_new_multi_action_user(multi_alert.action_user)
        multi_alert.counter = 1
    multi_alert.last_event_at = now()
    multi_alert.seen = False
    multi_alert.counter += 1
    multi_alert.add_new_multi_action_user(new_alert.action_user)
    multi_alert.generate_label()
    multi_alert.save()


def merge_new_alert_into_bundle_alert(new_alert, bundle_alert):
    """ Merges a newly arrived alert into an existing alert as bundle alert.
        The existing alert may yet still be a single alert  """
    # sanity check, cannot convert multi alerts
    if bundle_alert.type not in (NotificationAlert.TYPE_SINGLE_ALERT, NotificationAlert.TYPE_BUNDLE_ALERT):
        logger.warning('Inconsistency: Trying to create a bundle alert, but matched existing alert was a multi user alert!',
                       extra={'alert': str(bundle_alert)})
        return
    # make the old alert a bundle alert, add the new alert to the bundle and reset it to be current
    if bundle_alert.type == NotificationAlert.TYPE_SINGLE_ALERT:
        bundle_alert.type = NotificationAlert.TYPE_BUNDLE_ALERT
        bundle_alert.add_new_bundle_item(bundle_alert)
        bundle_alert.counter = 1
    bundle_alert.last_event_at = now()
    bundle_alert.seen = False
    bundle_alert.counter += 1
    bundle_alert.target_object = new_alert.target_object
    bundle_alert.add_new_bundle_item(new_alert)
    bundle_alert.generate_label()
    bundle_alert.save()

