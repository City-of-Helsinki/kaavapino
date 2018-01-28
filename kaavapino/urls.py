from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import TemplateView
from stronghold.views import StrongholdPublicMixin

from projects import views as projects_views

admin.autodiscover()


class PublicTemplateView(StrongholdPublicMixin, TemplateView):
    """TemplateView but with django stronghold public mixin"""


urlpatterns = [
    path('', PublicTemplateView.as_view(template_name='index.html')),
    path('accounts/', include('allauth.urls')),
    path('admin/', admin.site.urls),
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('projects/', include('projects.urls', namespace='projects')),
    path('reports/', projects_views.report_view, name='reports'),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
