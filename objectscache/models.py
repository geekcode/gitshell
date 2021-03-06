from django.db import models

class BaseModel(models.Model):
    create_time = models.DateTimeField(auto_now=False, auto_now_add=True, null=False)
    modify_time = models.DateTimeField(auto_now=True, auto_now_add=True, null=False)
    visibly = models.SmallIntegerField(default=0, null=False)

    class Meta:
        abstract = True
    
class Count(models.Model):
    count = models.IntegerField(default=0, null=False)     

class Select(models.Model):
    pass

class CacheKey:
    REPO_COMMIT_VERSION = 'repo.commit_version_%s'
    REPO_META = 'repo.meta_%s_%s'
    JOIN_CLIENT_IP = 'join.client_ip.%s'
