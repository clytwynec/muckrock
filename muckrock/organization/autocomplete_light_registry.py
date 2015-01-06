"""
Autocomplete registry for Organization
"""

import autocomplete_light
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404

from muckrock.organization.models import Organization

class UserAutocomplete(autocomplete_light.AutocompleteModelBase):
    """Creates an autocomplete field for picking agencies"""
    search_fields = ['username']
    attrs = {
        'placeholder': 'Search by username',
        'data-autocomplete-minimum-characters': 2
    }

class OrganizationAutocomplete(UserAutocomplete):
    """Adds organization-specific filtering for users"""
    def choices_for_request(self):
        query = self.request.GET.get('q', '')
        choices = self.choices.all()
        if query:
            choices = choices.filter(username__icontains=query)
        org_id = self.request.GET.get('orgId', '')
        if org_id: # exclude owner and members from choices
            organization = get_object_or_404(Organization, pk=org_id)
            owner = organization.owner
            profiles = organization.get_members()
            exclude_pks = [owner.pk] + [profile.user.pk for profile in profiles]
            choices = choices.exclude(pk__in=exclude_pks)
        return self.order_choices(choices)[0:self.limit_choices]

autocomplete_light.register(User, UserAutocomplete)
autocomplete_light.register(User, OrganizationAutocomplete)
