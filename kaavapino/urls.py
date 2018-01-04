from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

import projects.views

admin.autodiscover()


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', projects.views.index),
    path('<str:path>', projects.views.index),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
