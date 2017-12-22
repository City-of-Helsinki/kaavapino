from django.conf import settings
from django.contrib import admin
from django.urls import path
from django.conf.urls.static import static

import projects.views

admin.autodiscover()


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', projects.views.index),
    path('<str:path>', projects.views.index),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

