# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import logging
import datetime

from django.core.exceptions import ImproperlyConfigured
from django.core.urlresolvers import reverse
from django.utils import translation, formats
from django.utils.importlib import import_module
from django.utils.timezone import localtime
from django.utils.translation import ugettext_lazy as _
from django.template.loader import render_to_string

from cosinnus.conf import settings
from cosinnus.core.mail import get_common_mail_context, send_mail_or_fail
from cosinnus.core.registries.apps import app_registry
from cosinnus.models.group import CosinnusGroup, CosinnusPortal
from cosinnus.models.tagged import BaseTaggableObjectModel, BaseTagObject
from cosinnus_notifications.models import UserNotificationPreference,\
    NotificationEvent
from cosinnus.templatetags.cosinnus_tags import full_name, cosinnus_setting,\
    textfield
from cosinnus.utils.functions import ensure_dict_keys, resolve_attributes
from threading import Thread
from django.utils.safestring import mark_safe
from django.utils.html import strip_tags, urlize, escape
from django.contrib.contenttypes.models import ContentType
from cosinnus.utils.permissions import check_object_read_access,\
    check_user_can_receive_emails
from django.templatetags.static import static
from django.utils.encoding import force_text
from cosinnus.utils.group import get_cosinnus_group_model
from annoying.functions import get_object_or_None
from cosinnus.models.profile import GlobalUserNotificationSetting



logger = logging.getLogger('cosinnus')

ALL_NOTIFICATIONS_ID = 'notifications__all'
NO_NOTIFICATIONS_ID = 'notifications__none'

# the dict to store all configured notification signals and options
# notification settings from all cosinnus apps are added to this one
notifications = {
    ALL_NOTIFICATIONS_ID: {
        'label': _('All notifications'), # special, hardcoded notification preference has no further settings
        'mail_template': '',
        'subject_template': '',
        'signals': [],
    },  
    NO_NOTIFICATIONS_ID: {
        'label': _('No notifications'), # special, hardcoded notification preference has no further settings
        'mail_template': '',
        'subject_template': '',
        'signals': [], 
    },  
}

NOTIFICATION_REASONS = {
    'default': _('You are getting this notification because you are subscribed to these kinds of events in your project or group.'),
    'admin': _('You are getting this notification because you are an administrator of this project or group.'),
    'portal_admin': _('You are getting this notification because you are an administrator of this portal.'),
    'daily_digest': _('You are getting this email because you are subscribed to one or more daily notifications.'),
    'weekly_digest': _('You are getting this email because you are subscribed to one or more weekly notifications.'),
    'none': None, # the entire lower section won't be shown
}

REQUIRED_NOTIFICATION_ATTRIBUTE = object()
REQUIRED_NOTIFICATION_ATTRIBUTE_FOR_HTML = object()


# this is a lookup for all defaults of a notification definition
NOTIFICATIONS_DEFAULTS = {
    # Label for the notification option in user's preference
    'label': REQUIRED_NOTIFICATION_ATTRIBUTE, 
    # text-only mail body template. ignored for HTML mails
    'mail_template': REQUIRED_NOTIFICATION_ATTRIBUTE,
    # text-only mail subject template. ignored for HTML mails
    'subject_template': REQUIRED_NOTIFICATION_ATTRIBUTE,
    # a django signal on which to listen for
    'signals': [REQUIRED_NOTIFICATION_ATTRIBUTE],
    # should this notification preference be on by default (if the user has never changed the setting?)
    # this may be False or 0 (off), True or 1 (on, immediately), 2 (daily) or 3 (weekly)
    'default': False,
    # if True, won't be shown in the notification preference form view
    'hidden': False,
    # can this notification be sent to the objects creator?
    # default False, because most items aren't wanted to be known by the author creating them
    'allow_creator_as_audience': False,
    
    # does this notification support HTML emails and digest chunking?
    'is_html': False,
    # the snippet template for this notification's event (only used in digest emails, not instant ones)
    'snippet_template': 'cosinnus/html_mail/summary_item.html',
    # CSS class of the snippet template that customizes this notification by its type. usually the cosinnus app's name
    'snippet_type': 'news',
    # the HTML email's subject. use a gettext_lazy translatable string.
    # available variables: %(sender_name)s, %(team_name)s
    'subject_text': REQUIRED_NOTIFICATION_ATTRIBUTE_FOR_HTML,
    # little explanatory text of what happened here. (e.g. "new document", "upcoming event") 
    # this can some string substitution arguments, e.g. ``new post by %(sender_name)s``
    'event_text': _('New item'),
    # the explanatory text on a SINGLE notification of what happened. this should be a little more
    # elaborate than ``event_text`` and should usually be a full sentence (without the ending full stop).
    # default: if None or omitted, will use the contents of ``event_text``
    'notification_text': None,
    # event text for a subdivided item under the main one, if required
    'sub_event_text': None, 
    # Little text on the bottom of the mail explaining why the user received it. (only in instant mails)
    # see notifications.NOTIFICATION_REASONS
    'notification_reason': 'default', 
    # object attributes to fille the snippet template with. 
    # these will be looked up on the object as attribute or functions with no params
    # additionally, special attributes will be added to the object for the object during lookup-time:
    #     _sender: the User model object that caused the event
    #     _sender_name: the cleaned name of that User
    'data_attributes': {
        'object_name': 'title', # Main title and label of the notification object
        'object_url': 'get_absolute_url', # URL of the object
        'object_text': None, # further excerpt text of the object, for example for Event descriptions. if None: ignored
        'image_url': None, # image URL for the item. default if omitted is the event creator's user avatar
        'event_meta': None, # a small addendum to the grey event text where object data like datetimes can be displayed
        'sub_event_meta': None, # property of a sub-divided item below the main one, see doc above
        'sub_image_url': None, # property of a sub-divided item below the main one, see doc above
        'sub_object_text': None, # property of a sub-divided item below the main one, see doc above
    },
    # can be used to suffix the origin URL (group url for originating group) with parameters to take different actions when clicked
    'origin_url_suffix': '',
}


DIGEST_ITEM_TITLE_MAX_LENGTH = 50


def _find_notification(signal):
    """ Finds a configured notification for a received signal """
    for signal_id, options in notifications.items():
        if signal in options['signals']:
            return signal_id
    return None


def set_user_group_notifications_special(user, group, all_or_none_or_custom):
    """ Sets the user preference settings for a group to all or none or custom (deleting the special setting flag) """
    if not (all_or_none_or_custom.startswith("all_") or all_or_none_or_custom in ("none", "custom")):
        return
    
    al = get_object_or_None(UserNotificationPreference, user=user, group=group, notification_id=ALL_NOTIFICATIONS_ID)
    if al:
        if all_or_none_or_custom.startswith("all_"):
            setting_value = int(all_or_none_or_custom.split("_")[1])
            if setting_value in dict(UserNotificationPreference.SETTING_CHOICES).keys() and al.setting != setting_value:
                al.setting = setting_value
                al.save()
        else:
            al.delete()
    else:
        if all_or_none_or_custom.startswith("all_"):
            setting_value = int(all_or_none_or_custom.split("_")[1])
            if not setting_value in dict(UserNotificationPreference.SETTING_CHOICES).keys():
                setting_value = UserNotificationPreference.SETTING_NOW
            UserNotificationPreference.objects.create(user=user, group=group, notification_id=ALL_NOTIFICATIONS_ID, setting=setting_value)
    
    non = get_object_or_None(UserNotificationPreference, user=user, group=group, notification_id=NO_NOTIFICATIONS_ID)
    if non:
        if all_or_none_or_custom == "none":
            if not non.setting == UserNotificationPreference.SETTING_NOW:
                non.setting = UserNotificationPreference.SETTING_NOW
                non.save()
        else:
            non.delete()
    else:
        if all_or_none_or_custom == "none":
            UserNotificationPreference.objects.create(user=user, group=group, notification_id=NO_NOTIFICATIONS_ID, setting=UserNotificationPreference.SETTING_NOW)
        


def init_notifications():
    global notifications 
    
    all_items = [item for item in app_registry.items()]
    all_items.append( ('cosinnus', 'cosinnus', '') )
    for app, app_name, app_label in all_items:
        try:
            notification_module = import_module('%s.cosinnus_notifications' % app)
        except ImportError:
            continue
        if hasattr(notification_module, 'notifications'):
            for signal_id, options in notification_module.notifications.items():
                #label, template, signals
                signal_id = "%s__%s" % (app_name, signal_id)
                ensure_dict_keys(options, ['label', 'mail_template', 'subject_template', 'signals'], \
                    "The configured notification '%s' of app '%s' was missing the following dict keys: %%s" \
                    % (signal_id, app_name))
                
                options['app_name'] = app_name
                options['app_label'] = app_label
                # add missing notification settings
                for key, default in NOTIFICATIONS_DEFAULTS.items():
                    if options.get(key, None) is None:
                        if default == REQUIRED_NOTIFICATION_ATTRIBUTE or \
                                (options.get('is_html', False) and default == REQUIRED_NOTIFICATION_ATTRIBUTE_FOR_HTML):
                            raise ImproperlyConfigured('Notification options key "%s" in notification signal "%s" is required!' % (key, signal_id))
                        options[key] = default
                for datakey, datadefault in NOTIFICATIONS_DEFAULTS['data_attributes'].items():
                    if options['data_attributes'].get(datakey, None) is None:
                        options['data_attributes'][datakey] = datadefault
                    
                notifications[signal_id] = options
                # connect to signals
                for signal in options['signals']:
                    signal.connect(notification_receiver)
    logger.info('Cosinnus_notifications: init complete. Available notification signals: %s' % notifications.keys())


class NotificationsThread(Thread):

    def __init__(self, sender, user, obj, audience, notification_id, options):
        super(NotificationsThread, self).__init__()
        self.sender = sender
        self.user = user
        self.obj = obj
        self.audience = audience
        self.notification_id = notification_id
        self.options = options
        # this will be set if a notification is sent out to a user, 
        # so we know which preference was responsible and can link to it
        self.notification_preference_triggered = None
        # will be set at runtime
        self.group = None
    
    def is_notification_active(self, notification_id, user, group, alternate_settings_compare=[]):
        """ Checks against the DB if a user notifcation preference exists, and if so, if it is set to active """
        try:
            preference = UserNotificationPreference.objects.get(user=user, group=group, notification_id=notification_id)
            self.notification_preference_triggered = preference
            if len(alternate_settings_compare) == 0:
                return preference.setting == UserNotificationPreference.SETTING_NOW
            else:
                return preference.setting in alternate_settings_compare
        except UserNotificationPreference.DoesNotExist:
            # if not set in DB, check if preference is default on (and matching the setting value we're comparing to)
            if notification_id in notifications:
                default_preference_setting = notifications[notification_id].get('default', 0)
                if default_preference_setting:
                    if len(alternate_settings_compare) > 0:
                        return default_preference_setting in alternate_settings_compare
                    else:
                        return default_preference_setting == 1
        return False
        
    
    def check_user_wants_notification(self, user, notification_id, obj):
        """ Do multiple pre-checks and a DB check to find if the user wants to receive a mail for a 
            notification event. """
        
        # the first and foremost global check if we should ever send a mail at all
        if not check_user_can_receive_emails(user):
            return False
        # anonymous authors count as YES, used for recruiting users
        if not user.is_authenticated():
            return True
        # only active users that have logged in before accepted the TOS get notifications
        if not user.is_active:
            return False
        if not user.last_login:
            return False
        if not cosinnus_setting(user, 'tos_accepted'):
            return False
        
        # user cannot be object's creator unless explicitly specified
        if hasattr(obj, 'creator'):
            allow_creator_as_audience = False
            if notification_id in notifications:
                allow_creator_as_audience = notifications[notification_id].get('allow_creator_as_audience', False)
            if obj.creator == user and not allow_creator_as_audience:
                return False
        # user must be able to read object, unless it is a group (otherwise group invitations would never be sent)
        if not check_object_read_access(obj, user) and not (type(obj) is get_cosinnus_group_model() or issubclass(obj.__class__, get_cosinnus_group_model())):
            return False
        
        # global settings check, blanketing the finer grained checks
        global_setting = GlobalUserNotificationSetting.objects.get_for_user(user)
        if global_setting in [GlobalUserNotificationSetting.SETTING_NEVER, 
                GlobalUserNotificationSetting.SETTING_DAILY, GlobalUserNotificationSetting.SETTING_WEEKLY]:
            # user either wants no notification or a digest (the event for which is saved elsewhere)
            return False
        if global_setting == GlobalUserNotificationSetting.SETTING_NOW:
            return True
        # otherwise, the global setting is set to 'individual', so commence the other checks
        
        if self.is_notification_active(NO_NOTIFICATIONS_ID, user, self.group):
            # user didn't want notification because he wants none ever for this group!
            return False
        elif self.is_notification_active(ALL_NOTIFICATIONS_ID, user, self.group):
            # user wants notification because he wants all for this group!
            return True
        elif self.is_notification_active(ALL_NOTIFICATIONS_ID, user, self.group, 
                     alternate_settings_compare=[UserNotificationPreference.SETTING_DAILY, UserNotificationPreference.SETTING_WEEKLY]):
            # user wants all notifications for this group, but daily/weekly (the event itself will be saved into an object elsewhere)!
            return False
        elif self.is_notification_active(notification_id, user, self.group, 
                     alternate_settings_compare=[UserNotificationPreference.SETTING_DAILY, UserNotificationPreference.SETTING_WEEKLY]):
            # user wants this notification for this group, but daily/weekly (the event itself will be saved into an object elsewhere)!
            return False
        else:
            # the individual setting for this notification type and group is in effect:
            return self.is_notification_active(notification_id, user, self.group)


    def run(self):
        from cosinnus.utils.context_processors import cosinnus as cosinnus_context
        
        # set group, inferred from object
        if type(self.obj) is CosinnusGroup or issubclass(self.obj.__class__, CosinnusGroup):
            self.group = self.obj
        elif issubclass(self.obj.__class__, BaseTaggableObjectModel):
            self.group = self.obj.group
        elif hasattr(self.obj, 'group'):
            self.group = self.obj.group
        else:
            raise ImproperlyConfigured('A signal for a notification was received, but the supplied object\'s group could not be determined. \
                If your object is not a CosinnusGroup or a BaseTaggableObject, you can fix this by patching a ``group`` attribute onto it.')
        
        # we wrap the info in a (non-persisted) NotificationEvent to be compatible with the rendering method
        notification_event = NotificationEvent(group=self.group, user=self.user, notification_id=self.notification_id, target_object=self.obj)
        setattr(notification_event, '_target_object', self.obj) # this helps reduce lookups by local caching the generic foreign key object
        
        for receiver in self.audience:
            if self.check_user_wants_notification(receiver, self.notification_id, self.obj):
                
                # switch language to user's preference language
                cur_language = translation.get_language()
                try:
                    if hasattr(receiver, 'cosinnus_profile'): # receiver can be a virtual user
                        translation.activate(getattr(receiver.cosinnus_profile, 'language', settings.LANGUAGES[0][0]))
                    elif hasattr(self.user, 'cosinnus_profile'): # if receiver is a virtual user, set language to sender's
                        translation.activate(getattr(self.user.cosinnus_profile, 'language', settings.LANGUAGES[0][0]))
                    
                    portal = CosinnusPortal.get_current()
                    site = portal.site
                    domain = portal.get_domain()
                    
                    # if we know the triggering preference, we can link to it directly via ULR anchors
                    url_suffix = ''
                    if self.notification_preference_triggered:
                        group_pk = self.notification_preference_triggered.group_id
                        pref_arg = ''
                        if self.notification_preference_triggered.notification_id not in (NO_NOTIFICATIONS_ID, ALL_NOTIFICATIONS_ID):
                            pref_arg = 'highlight_pref=%d:%s&' % (group_pk, self.notification_preference_triggered.notification_id)
                        url_suffix = '?%shighlight_choice=%d#notif_choice_%d' % (pref_arg, group_pk, group_pk)
                    preference_url = '%s%s%s' % (domain, reverse('cosinnus:notifications'), url_suffix)
                    
                    
                    
                    is_html = self.options.get('is_html', False)
                    
                    if is_html:
                        template = '/cosinnus/html_mail/notification.html'
                        portal_name =  _(settings.COSINNUS_BASE_PAGE_TITLE_TRANS)
                        
                        reason = NOTIFICATION_REASONS[self.options.get('notification_reason')] 
                        portal_image_url = '%s%s' % (domain, static('img/logo-icon.png'))
                        
                        # render the notification item (and get back some data from the event)
                        notification_item_html, data = render_digest_item_for_notification_event(notification_event, return_data=True)
                        topic = data.get('notification_text', None) or data.get('event_text')
                        subject = self.options.get('subject_text') % data.get('string_variables')
                        
                        context = {
                            'site': site,
                            'site_name': site.name,
                            'domain_url': domain,
                            'portal_url': domain,
                            'portal_image_url': portal_image_url,
                            'portal_name': portal_name,
                            'receiver': receiver, 
                            'addressee': mark_safe(strip_tags(full_name(receiver))), 
                            'topic': topic,
                            'prefs_url': mark_safe(preference_url),
                            
                            'notification_reason': reason,
                            
                            'origin_name': self.group['name'],
                            'origin_url': self.group.get_absolute_url() + self.options.get('origin_url_suffix', ''),
                            'origin_image_url': domain + (self.group.get_avatar_thumbnail_url() or static('images/group-avatar-placeholder.png')),
                            
                            'notification_body': None, # this is a body text that can be used for group description or similar
                            
                            'notification_item_html': mark_safe(notification_item_html),
                        }
                    
                    else:
                        
                        template = self.options['mail_template']
                        subj_template = self.options['subject_template']
                        if self.sender.request:
                            context = get_common_mail_context(self.sender.request)
                            context.update(cosinnus_context(self.sender.request))
                        else:
                            context = {} # no request in sender
                        
                        context.update({
                            'receiver':receiver, 
                            'receiver_name':mark_safe(strip_tags(full_name(receiver))), 
                            'sender':self.user, 
                            'sender_name':mark_safe(strip_tags(full_name(self.user))), 
                            'object':self.obj, 
                            'notification_settings_url':mark_safe(preference_url)
                        })
                        
                        # additional context for BaseTaggableObjectModels
                        context.update({'team_name': mark_safe(strip_tags(self.group['name']))})
                        if issubclass(self.obj.__class__, BaseTaggableObjectModel):
                            context.update({'object_name': mark_safe(strip_tags(self.obj.title))})
                        try:
                            context.update({'object_url':self.obj.get_absolute_url()})
                        except:
                            pass
                        subject = render_to_string(subj_template, context)
                    
                    
                    send_mail_or_fail(receiver.email, subject, template, context, is_html=is_html)
                    
                finally:
                    translation.activate(cur_language)
        
        if self.audience:
            # create a new NotificationEvent that saves this event for digest re-generation
            content_type = ContentType.objects.get_for_model(self.obj.__class__)
            notifevent = NotificationEvent.objects.create(
                content_type=content_type,
                object_id=self.obj.id,
                group=self.group,
                user=self.user,
                notification_id=self.notification_id,
                audience=',%s,' % ','.join([str(receiver.id) for receiver in self.audience]),
            )
          
        return


def render_digest_item_for_notification_event(notification_event, return_data=False):
    """ Renders the HTML of a single notification event for a receiving user """
    
    try:
        obj = getattr(notification_event, '_target_object', notification_event.target_object)
        options = notifications[notification_event.notification_id]
        
        # stub for missing notification for this digest
        if not options.get('is_html', False):
            logger.exception('Missing HTML snippet configuration for digest encountered for notification setting "%s". Skipping this notification type in this digest!' % notification_event.notification_id)
            return ''
            """
            return '<div>stub: event "%s" with object "%s" from user "%s"</div>' % (
                notification_event.notification_id,
                getattr(obj, 'text', getattr(obj, 'title', getattr(obj, 'name', 'NOARGS'))),
                notification_event.user.get_full_name(),
            )
            """
        data_attributes = options['data_attributes']
        
        sender_name = mark_safe(strip_tags(full_name(notification_event.user)))
        # add special attributes to object
        obj._sender_name = sender_name
        obj._sender = notification_event.user
        
        object_name = resolve_attributes(obj, data_attributes['object_name'], 'title')
        string_variables = {
            'sender_name': escape(sender_name),
            'object_name': escape(object_name),
            'portal_name': escape(_(settings.COSINNUS_BASE_PAGE_TITLE_TRANS)),
            'team_name': escape(notification_event.group['name']),
        }
        event_text = options['event_text']
        notification_text = options['notification_text'] or options['event_text']
        sub_event_text = options['sub_event_text']
        
        event_text = mark_safe((event_text % string_variables)) if event_text else None
        notification_text = mark_safe((notification_text % string_variables)) if notification_text else None
        sub_event_text = mark_safe((sub_event_text % string_variables)) if sub_event_text else None
        
        sub_image_url = resolve_attributes(obj, data_attributes['sub_image_url'])
        
        # full escape and markup conversion
        object_text = textfield(resolve_attributes(obj, data_attributes['object_text']))
        sub_object_text = textfield(resolve_attributes(obj, data_attributes['sub_object_text']))
        
        content_rows = []
        if not (sub_event_text and sub_image_url):
            # on full-page item displays (where the main object isn't a subtexted item, like a comment),
            # we display additional data for that item, if defined in the Model's `render_additional_notification_content_rows()`
            render_func = getattr(obj, "render_additional_notification_content_rows", None)
            if callable(render_func):
                content_rows = render_func()
            
            
        data = {
            'type': options['snippet_type'],
            'event_text': event_text,
            'notification_text': notification_text,
            'snippet_template': options['snippet_template'],
            
            'event_meta': resolve_attributes(obj, data_attributes['event_meta']),
            'object_name': object_name,
            'object_url': resolve_attributes(obj, data_attributes['object_url'], 'get_absolute_url'),
            'object_text': object_text,
            'image_url': resolve_attributes(obj, data_attributes['image_url']),
            'content_rows': content_rows,
            
            'sub_event_text': sub_event_text,
            'sub_event_meta': resolve_attributes(obj, data_attributes['sub_event_meta']),
            'sub_image_url': sub_image_url,
            'sub_object_text': sub_object_text,
            
            'string_variables': string_variables,
        }
        #object_text
        #sub_object_text
        
        
        # clean some attributes
        if not data['object_name']:
            data['object_name'] = _('Untitled')
        if len(data['object_name']) > DIGEST_ITEM_TITLE_MAX_LENGTH:
            data['object_name'] = data['object_name'][:DIGEST_ITEM_TITLE_MAX_LENGTH-3] + '...'
        # default for image_url is the notifcation event's causer
        if not data['image_url']:
            data['image_url'] = CosinnusPortal.get_current().get_domain() + \
                 (notification_event.user.cosinnus_profile.get_avatar_thumbnail_url() or static('images/jane-doe.png'))
        # ensure URLs are absolute
        for url_field in ['image_url', 'object_url', 'sub_image_url']:
            url = data[url_field]
            if url and not url.startswith('http'):
                data[url_field] = CosinnusPortal.get_current().get_domain() + data[url_field]
                
        # humanize all datetime objects
        for key, val in data.items():
            if isinstance(val, datetime.datetime):
                data[key] = formats.date_format(localtime(val), 'SHORT_DATETIME_FORMAT')
                
        item_html = render_to_string(options['snippet_template'], context=data)
        if return_data:
            return item_html, data
        else:
            return item_html
    
    except Exception, e:
        logger.exception('Error while rendering a digest item for a digest email. Exception in extra.', extra={'exception': force_text(e)})
    return ''


def notification_receiver(sender, user, obj, audience, **kwargs):
    """ Generic receiver function for all notifications 
        sender: the main object that is being updated / created
        user: the user that modified the object and caused the event
        audience: a list of users that are potential targets for the event 
    """
    signal = kwargs['signal']
    # find out configured signal id for the signal we received
    notification_id = _find_notification(signal)
    if not notification_id:
        return
    options = notifications[notification_id]
    
    # update / overwrite options with extra kwargs sent by the signalling code piece individually
    if 'extra' in kwargs: 
        # deepcopy does not work here, so create a new dict
        copy_options = {}
        copy_options.update(options)
        copy_options.update(kwargs['extra'])
        options = copy_options
    
    # sanity check: only send to active users that have an email set (or is anonymous, so we can send emails to non-users)
    audience = [aud_user for aud_user in audience if ((aud_user.is_active or not aud_user.is_authenticated()) and aud_user.email)]
    
    notification_thread = NotificationsThread(sender, user, obj, audience, notification_id, options)
    notification_thread.start()

