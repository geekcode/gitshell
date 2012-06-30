from django.conf.urls.defaults import patterns, include, url

urlpatterns = patterns('gitshell',
    # gitshell web app, nginx port 8000, proxy by haproxy, public
    url(r'^/?$', 'index.views.index'),
    # skills
    # url(r'^skills/?$', 'skills.views.skills'),

    # stats
    url(r'^stats/?$', 'stats.views.stats'),

    # ajax
    url(r'^ajax/feed/ids/?$', 'feed.views.feedbyids'),
    url(r'^ajax/repo/(\w+)/(\w+)/refs/?$', '.views.repo_refs'),
    url(r'^ajax/repo/(\w+)/(\w+)/diff/(\w+)/(\w+)/([a-zA-Z0-9_\.\-/]*)$', '.views.repo_diff'),
    url(r'^ajax/network/watch/(\w+)/', '.views.network_watch'),
    url(r'^ajax/network/unwatch/(\w+)/', '.views.network_unwatch'),

    # gsuser
    url(r'^home/?$', 'feed.views.home'),
    url(r'^home/feed/?$', 'feed.views.feed'),
    url(r'^home/git/?$', 'feed.views.git'),
    url(r'^home/issues/?$', 'feed.views.issues'),
    url(r'^home/explore/?$', 'feed.views.explore'),
    url(r'^home/notif/?$', 'feed.views.notif'),
    url(r'^login/?$', 'gsuser.views.login'),
    url(r'^logout/?$', 'gsuser.views.logout'),
    url(r'^join/?(\w+)?/?$', 'gsuser.views.join'),
    url(r'^resetpassword/?(\w+)?/?$', 'gsuser.views.resetpassword'),

    # help
    url(r'^help/?$', 'help.views.default'),
    url(r'^help/quickstart/?$', 'help.views.quickstart'),

    # settings
    url(r'^settings/?$', 'gssettings.views.profile'),
    url(r'^settings/profile/?$', 'gssettings.views.profile'),
    url(r'^settings/changepassword/?$', 'gssettings.views.changepassword'),
    url(r'^settings/sshpubkey/?$', 'gssettings.views.sshpubkey'),
    url(r'^settings/sshpubkey/remove/?$', 'gssettings.views.sshpubkey_remove'),
    url(r'^settings/email/?$', 'gssettings.views.email'),
    url(r'^settings/repo/?$', 'gssettings.views.repo'),
    url(r'^settings/destroy/?$', 'gssettings.views.destroy'),

    # gitshell openssh keyauth and dist, private for subnetwork access by iptables, nginx port 9000
    url(r'^private/keyauth/([A-Za-z0-9:]+)/?$', 'keyauth.views.pubkey'),
    url(r'^private/keyauth/([A-Za-z0-9:]+)/([A-Za-z0-9_ \-\'"\/]+)$', 'keyauth.views.keyauth'),
    url(r'^private/dist//(\w+)/(\w+)/?$', 'dist.views.repo'),
    url(r'^private/dist/refresh/?$', 'dist.views.refresh'),
    url(r'^private/dist/echo/?$', 'dist.views.echo'),

    # third part
    url(r'^captcha/', include('captcha.urls')),

    # write middleware to rewrite urlconf, by add 'urlconf' attribute to HttpRequest
    # gsuser
    url(r'^(\w+)/?$', 'gsuser.views.user'),
    # 
    url(r'^(\w+)//?$', 'repo.views.user_repo'),
    url(r'^(\w+)//(\d+)/?$', 'repo.views.user_repo_paging'),
    url(r'^\w+//edit/(\d+)/?$', 'repo.views.edit'),
    url(r'^(\w+)/(\w+)/?$', '.views.repo'),
    url(r'^(\w+)/(\w+)/tree/?$', '.views.repo_default_tree'),
    url(r'^(\w+)/(\w+)/tree/([a-zA-Z0-9_\.\-]+)/([a-zA-Z0-9_\.\-/]*)$', '.views.repo_tree'),
    url(r'^(\w+)/(\w+)/raw/tree/([a-zA-Z0-9_\.\-]+)/([a-zA-Z0-9_\.\-/]*)$', '.views.repo_raw_tree'),
    url(r'^(\w+)/(\w+)/commits/?$', '.views.repo_default_commits'),
    url(r'^(\w+)/(\w+)/commits/([a-zA-Z0-9_\.\-]+)/([a-zA-Z0-9_\.\-/]*)$', '.views.repo_commits'),
	url(r'^(\w+)/(\w+)/issues/?$', '.views.repo_issues'),
	url(r'^(\w+)/(\w+)/issues/create/?$', '.views.repo_create_issues'),
	url(r'^(\w+)/(\w+)/issues/delete/(\w+)/?$', '.views.repo_delete_issues'),
	url(r'^(\w+)/(\w+)/issues/list/(\w+)/(\w+)/(\w+)/(\w+)/(\w+)/(\w+)/?$', '.views.repo_list_issues'),
	url(r'^(\w+)/(\w+)/issues/create/comment/(\w+)/?$', '.views.repo_create_comment'),
	url(r'^(\w+)/(\w+)/issues/delete/comment/(\w+)/?$', '.views.repo_delete_comment'),
    url(r'^(\w+)/(\w+)/network/?$', '.views.repo_network'),
    url(r'^(\w+)/(\w+)/clone_branches/?$', '.views.repo_clone_branches'),
    url(r'^(\w+)/(\w+)/stats/?$', '.views.repo_stats'),
)
