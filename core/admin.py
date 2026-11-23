from django.contrib import admin
from django.db import models as dj
from . import models
for n in dir(models):
    m = getattr(models, n)
    if isinstance(m, type) and issubclass(m, dj.Model) and m.__module__ == models.__name__:
        admin.site.register(m)
