"""
URL mappings for the crowdsource app
"""

from django.conf.urls import url
from django.views.generic.base import RedirectView

from muckrock.crowdsource import views

urlpatterns = [
        url(r'^(?P<slug>[-\w]+)-(?P<idx>\d+)/$',
            views.CrowdsourceDetailView.as_view(),
            name='crowdsource-detail',
            ),
        url(r'^(?P<slug>[-\w]+)-(?P<idx>\d+)/assignment/$',
            views.CrowdsourceFormView.as_view(),
            name='crowdsource-assignment',
            ),
        url(r'^$',
            RedirectView.as_view(url='/crowdsource/list'),
            name='crowdsource-index',
            ),
        url(r'^list/$',
            views.CrowdsourceListView.as_view(),
            name='crowdsource-list',
            ),
        url(r'^create/$',
            views.CrowdsourceCreateView.as_view(),
            name='crowdsource-create',
            ),
        ]