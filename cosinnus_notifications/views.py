# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.core.urlresolvers import reverse_lazy
from django.contrib import messages
from django.http.response import HttpResponseRedirect, HttpResponseNotAllowed,\
    HttpResponseForbidden
from django.utils.translation import ugettext_lazy as _
from django.views.generic.edit import UpdateView

from cosinnus.conf import settings
from cosinnus.core.decorators.views import require_logged_in
from cosinnus_notifications.models import UserNotificationPreference
from cosinnus_notifications.notifications import notifications,\
    ALL_NOTIFICATIONS_ID, NO_NOTIFICATIONS_ID,\
    set_user_group_notifications_special
from cosinnus.models.group import CosinnusGroup
from django.views.decorators.csrf import csrf_protect
from cosinnus.models.profile import GlobalUserNotificationSetting
from django.db import transaction



class NotificationPreferenceView(UpdateView):
    
    object = {}
    model = UserNotificationPreference
    template_name = 'cosinnus_notifications/notifications_form.html'
    success_url = reverse_lazy('cosinnus:notifications')
    message_success = _('Your notification preferences were updated successfully.')
    
    @require_logged_in()
    def dispatch(self, request, *args, **kwargs):
        return super(NotificationPreferenceView, self).dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        """
        Handles GET requests and instantiates a blank version of the form.
        """
        self.user = self.request.user
        return self.render_to_response(self.get_context_data())
    
    def post(self, request, *args, **kwargs):
        """
        Handles POST requests, instantiating a form instance with the passed
        POST variables and then checked for validity.
        """
        with transaction.atomic():
            # save language preference:
            language = request.POST.get('language', None)
            if language is not None and language in (lang for lang, label in settings.LANGUAGES):
                request.user.cosinnus_profile.language = language
                request.user.cosinnus_profile.save(update_fields=['language'])
            
            # save global notification setting
            global_setting = int(request.POST.get('global_setting', '-1'))
            if global_setting >= 0 and global_setting in (sett for sett, label in GlobalUserNotificationSetting.SETTING_CHOICES):
                setting_obj = GlobalUserNotificationSetting.objects.get_object_for_user(request.user)
                setting_obj.setting = global_setting
                setting_obj.save()
            
            # only update the individual group settings if user selected the individual global setting
            if global_setting == GlobalUserNotificationSetting.SETTING_GROUP_INDIVIDUAL:            
                for name, value in request.POST.items():
                    # we go through all values POSTed to us. some of these are the settings from the dropdown
                    # box (all / none / custom), some of them are the individual custom preference choices
                    # for a group.
                    # depending of the dropdown setting we set the global all/none setting and ignore the custom
                    # values, or if set to custom, delete any global all/none preference entries for that group
                    # and save the individual preference settings for that group
                    if not name.startswith('notif_'):
                        continue
                    if name.startswith('notif_choice:'):
                        group_id = int(name.split(':')[1])
                        group = CosinnusGroup.objects.get_cached(pks=group_id)
                        set_user_group_notifications_special(request.user, group, value)
                    elif name.startswith('notif_option:'):
                        # if we are looking at a group item, check if the choice field is set to custom,
                        # otherwise ignore it
                        value = int(value)
                        _, group_id, notification_id = name.split(':')
                        if request.POST.get('notif_choice:%s' % group_id, None) == 'custom':
                            # save custom settings if the main switch for custom is enabled:
                            group = CosinnusGroup.objects.get_cached(pks=int(group_id))
                            # save / erase setting
                            try:
                                pref = UserNotificationPreference.objects.get(user=request.user, group=group, notification_id=notification_id)
                                if value in dict(UserNotificationPreference.SETTING_CHOICES).keys() and value != pref.setting:
                                    pref.setting = value
                                    pref.save()
                            except UserNotificationPreference.DoesNotExist:
                                pref = UserNotificationPreference.objects.create(user=request.user, group=group, notification_id=notification_id, setting=value)
        
        messages.success(request, self.message_success)
        return HttpResponseRedirect(self.success_url)
    
    def get_queryset(self):
        """
            Get the queryset of notifications
        """
        self.queryset = self.model._default_manager.filter(user=self.request.user)
        return self.queryset
    
    def get_context_data(self, **kwargs):
        """
        Insert the single object into the context dict.
        """
        context = super(UpdateView, self).get_context_data(**kwargs)
        
        # build lookup dict for all active existing preferences vs groups
        prefs = {} # 'groupid:notification_id' 
        for pref in self.get_queryset():
            prefs['%s:%s' % (pref.group.pk, pref.notification_id)] = pref.setting
        
        group_rows = [] # [(group, notification_rows, choice_selected), ...]
        # get groups, grouped by their 
        groups = CosinnusGroup.objects.get_for_user(self.user)
        groups = sorted(groups, key=lambda group: ((group.parent.name +'_' if group.parent else '') + group.name).lower())
        
        for group in groups:
            choice_selected = "custom"
            notification_rows = [] # [[id, label, value, app, app_label], ...]
            for notification_id, options in notifications.items():
                # do not show hidden notifications
                if options.get('hidden', False):
                    continue
                notif_id = '%s:%s' % (group.pk, notification_id)
                if notification_id == ALL_NOTIFICATIONS_ID:
                    if notif_id in prefs:
                        choice_selected = "all_%d" % prefs[notif_id]
                    continue
                if notification_id == NO_NOTIFICATIONS_ID:
                    if notif_id in prefs:
                        choice_selected = "none"
                    continue
                if notif_id in prefs:
                    value = prefs[notif_id]
                else:
                    value = int(options.get('default', False))
                # check for default if false, 
                notification_rows.append([notif_id, options['label'], value, options['app_name'], options['app_label']])
            
            # add a "fake" project's group header row to add a missing group,
            # if the user was not member of the group, but member in a child project
            if group.parent and group_rows and not group_rows[-1][0].parent and not group_rows[-1][0] == group.parent:
                group_rows.append( (group.parent, False, False) )
            notification_rows = sorted(notification_rows, key=lambda row: row[4].lower())
            group_rows.append( (group, notification_rows, choice_selected) )
        
        global_setting_choices = GlobalUserNotificationSetting.SETTING_CHOICES
        global_setting_selected = GlobalUserNotificationSetting.objects.get_for_user(self.request.user) 
        
        context.update({
            #'object_list': self.queryset,
            'grouped_notifications': group_rows,
            'user': self.request.user,
            'all_notifications_id': ALL_NOTIFICATIONS_ID,
            'no_notifications_id': NO_NOTIFICATIONS_ID,
            'language_choices': settings.LANGUAGES,
            'language_selected': self.request.user.cosinnus_profile.language,
            'global_setting_choices': global_setting_choices,
            'global_setting_selected': global_setting_selected,
            'notification_choices': UserNotificationPreference.SETTING_CHOICES,
        })
        return context
    
    
notification_preference_view = NotificationPreferenceView.as_view()


@csrf_protect
def notification_reset_view(request):
    if not request.method=='POST':
        return HttpResponseNotAllowed(['POST'])
    if not request.user.is_authenticated():
        return HttpResponseForbidden('You must be logged in to do that!')
    
    # deleting all preferences resets the user's notifications to default
    UserNotificationPreference.objects.filter(user=request.user).delete()
    
    messages.success(request, _('Your notifications preferences were reset to default!'))
    return HttpResponseRedirect(reverse_lazy('cosinnus:notifications'))
    
    
from cosinnus_notifications.hooks import *
