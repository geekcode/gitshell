# -*- coding: utf-8 -*-  
import os, re, sys
import json, time, urllib
import shutil, copy, random
from sets import Set
from datetime import datetime, timedelta
from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.template import RequestContext
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.contrib.auth.models import User
from django.core.cache import cache
from django.shortcuts import render_to_response
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError
from django.utils.html import escape
from django.forms.models import model_to_dict
from gitshell.feed.feed import AttrKey, FeedAction
from gitshell.feed.models import FeedManager, FEED_TYPE, NOTIF_TYPE
from gitshell.repo.Forms import RepoForm, RepoMemberForm
from gitshell.repo.githandler import GitHandler
from gitshell.repo.models import Repo, RepoManager, PullRequest, PULL_STATUS, KEEP_REPO_NAME
from gitshell.gsuser.models import GsuserManager
from gitshell.gsuser.decorators import repo_permission_check, repo_source_permission_check
from gitshell.team.models import TeamManager
from gitshell.stats import timeutils
from gitshell.stats.models import StatsManager
from gitshell.settings import SECRET_KEY, REPO_PATH, GIT_BARE_REPO_PATH, DELETE_REPO_PATH, PULLREQUEST_REPO_PATH, logger
from gitshell.daemon.models import EventManager
from gitshell.objectscache.models import CacheKey
from gitshell.viewtools.views import json_httpResponse
from gitshell.thirdparty.views import github_oauth_access_token, github_get_thirdpartyUser, github_authenticate, github_list_repo, dropbox_share_direct

lang_suffix = {'applescript': 'AppleScript', 'as3': 'AS3', 'bash': 'Bash', 'sh': 'Bash', 'cfm': 'ColdFusion', 'cfc': 'ColdFusion', 'cpp': 'Cpp', 'cxx': 'Cpp', 'c': 'Cpp', 'h': 'Cpp', 'cs': 'CSharp', 'css': 'Css', 'dpr': 'Delphi', 'dfm': 'Delphi', 'pas': 'Delphi', 'diff': 'Diff', 'patch': 'Diff', 'erl': 'Erlang', 'groovy': 'Groovy', 'fx': 'JavaFX', 'jfx': 'JavaFX', 'java': 'Java', 'js': 'JScript', 'pl': 'Perl', 'py': 'Python', 'php': 'Php', 'psl': 'PowerShell', 'rb': 'Ruby', 'sass': 'Sass', 'scala': 'Scala', 'sql': 'Sql', 'vb': 'Vb', 'xml': 'Xml', 'xhtml': 'Xml', 'html': 'Xml', 'htm': 'Xml', 'go': 'Go'}
brush_aliases = {'AppleScript': 'applescript', 'AS3': 'actionscript3', 'Bash': 'shell', 'ColdFusion': 'coldfusion', 'Cpp': 'cpp', 'CSharp': 'csharp', 'Css': 'css', 'Delphi': 'delphi', 'Diff': 'diff', 'Erlang': 'erlang', 'Groovy': 'groovy', 'JavaFX': 'javafx', 'Java': 'java', 'JScript': 'javascript', 'Perl': 'perl', 'Php': 'php', 'Plain': 'plain', 'PowerShell': 'powershell', 'Python': 'python', 'Ruby': 'ruby', 'Sass': 'sass', 'Scala': 'scala', 'Sql': 'sql', 'Vb': 'vb', 'Xml': 'xml', 'Go': 'go'}
PULLREQUEST_COMMIT_MESSAGE_TMPL = 'Merge branch %s of https://gitshell.com/%s/%s/ into %s, see https://gitshell.com/%s/%s/pull/%s/, %s'
@login_required
def user_repo(request, user_name):
    return user_repo_paging(request, user_name, 0)

@login_required
def user_repo_paging(request, user_name, pagenum):
    user = GsuserManager.get_user_by_name(user_name)
    userprofile = GsuserManager.get_userprofile_by_name(user_name)
    if user is None:
        raise Http404
    raw_repo_list = RepoManager.list_repo_by_userId(user.id, 0, 100)
    repo_list = raw_repo_list
    if user.id != request.user.id:
        repo_list = [x for x in raw_repo_list if x.auth_type != 2]
    repo_feed_map = {}
    feedAction = FeedAction()
    i = 0
    for repo in repo_list:
        repo_feed_map[str(repo.name)] = []
        feeds = feedAction.get_repo_feeds(repo.id, 0, 4)
        for feed in feeds:
            repo_feed_map[str(repo.name)].append(feed[0])
        i = i + 1
        if i > 10:
            break
    # fix on error detect
    pubrepo = 0
    for repo in raw_repo_list:
        if repo.auth_type == 0 or repo.auth_type == 1:
            pubrepo = pubrepo + 1
    prirepo = len(raw_repo_list) - pubrepo
    if pubrepo != userprofile.pubrepo or prirepo != userprofile.prirepo:
        userprofile.pubrepo = pubrepo
        userprofile.prirepo = prirepo
        userprofile.save()

    response_dictionary = {'mainnav': 'repo', 'user_name': user_name, 'gsuser': user, 'gsuserprofile': userprofile, 'repo_list': repo_list, 'repo_feed_map': repo_feed_map}
    return render_to_response('repo/user_repo.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

@repo_permission_check
def repo(request, user_name, repo_name):
    refs = None; path = '.'; current = 'index'
    return ls_tree(request, user_name, repo_name, refs, path, current)

@repo_permission_check
def tree_default(request, user_name, repo_name):
    refs = None; path = '.'; current = 'tree'
    return ls_tree(request, user_name, repo_name, refs, path, current)
    
@repo_permission_check
def tree(request, user_name, repo_name, refs, path):
    current = 'tree'
    return ls_tree(request, user_name, repo_name, refs, path, current)

@repo_permission_check
@repo_source_permission_check
def raw_blob(request, user_name, repo_name, refs, path):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None or path.endswith('/'):
        raise Http404
    refs = _get_current_refs(request.user, repo, refs, True)
    gitHandler = GitHandler()
    abs_repopath = repo.get_abs_repopath()
    commit_hash = gitHandler.get_commit_hash(repo, abs_repopath, refs)
    blob = gitHandler.repo_cat_file(abs_repopath, commit_hash, path)
    return HttpResponse(blob, content_type="text/plain; charset=utf-8")

@repo_permission_check
def ls_tree(request, user_name, repo_name, refs, path, current):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    refs = _get_current_refs(request.user, repo, refs, True)
    if path is None or path == '':
        path = '.'
    abs_repopath = repo.get_abs_repopath()
    gitHandler = GitHandler()
    commit_hash = gitHandler.get_commit_hash(repo, abs_repopath, refs)
    tree = {}
    if repo.status == 0 and (repo.auth_type == 0 or RepoManager.is_repo_member(repo, request.user)):
        if path == '.' or path.endswith('/'):
            tree = gitHandler.repo_ls_tree(abs_repopath, commit_hash, path)
    readme_md = None
    if tree and 'has_readme' in tree and tree['has_readme']:
        readme_md = gitHandler.repo_cat_file(abs_repopath, commit_hash, tree['readme_file'])
    response_dictionary = {'mainnav': 'repo', 'current': current, 'path': path, 'tree': tree, 'readme_md': readme_md}
    response_dictionary.update(get_common_repo_dict(request, repo, user_name, repo_name, refs))
    return render_to_response('repo/tree.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

@repo_permission_check
def blob(request, user_name, repo_name, refs, path):
    current = 'blob'
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None or path is None or path == '':
        raise Http404
    refs = _get_current_refs(request.user, repo, refs, True)
    abs_repopath = repo.get_abs_repopath()
    gitHandler = GitHandler()
    commit_hash = gitHandler.get_commit_hash(repo, abs_repopath, refs)
    blob = u''; lang = 'Plain'; brush = 'plain'
    if repo.auth_type == 0 or RepoManager.is_repo_member(repo, request.user):
        paths = path.split('.')
        if len(paths) > 0:
            suffix = paths[-1]
            if suffix in lang_suffix and lang_suffix[suffix] in brush_aliases:
                lang = lang_suffix[suffix]
                brush = brush_aliases[lang]
        blob = gitHandler.repo_cat_file(abs_repopath, commit_hash, path)
    is_markdown = path.endswith('.markdown') or path.endswith('.md') or path.endswith('.mkd')
    response_dictionary = {'mainnav': 'repo', 'current': current, 'path': path, 'blob': blob, 'lang': lang, 'brush': brush, 'is_markdown': is_markdown}
    response_dictionary.update(get_common_repo_dict(request, repo, user_name, repo_name, refs))
    return render_to_response('repo/blob.html',
                          response_dictionary,
                          context_instance=RequestContext(request))
    
@repo_permission_check
def commit(request, user_name, repo_name, commit_hash):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    refs = _get_current_refs(request.user, repo, None, True)
    path = '.'; current = 'commits'
    gitHandler = GitHandler()
    commits = gitHandler.repo_log_file(repo.get_abs_repopath(), '0000000', commit_hash, 1, path)
    _fillwith_commits(commits)
    commit = None
    if len(commits) > 0:
        commit = commits[0]
    response_dictionary = {'mainnav': 'repo', 'current': current, 'commit_hash': commit_hash, 'commit': commit}
    response_dictionary.update(get_common_repo_dict(request, repo, user_name, repo_name, refs))
    return render_to_response('repo/commit.html',
                          response_dictionary,
                          context_instance=RequestContext(request))
    
@repo_permission_check
def commits_default(request, user_name, repo_name):
    refs = None; path = '.'
    return commits(request, user_name, repo_name, refs, path)
    
@repo_permission_check
def commits(request, user_name, repo_name, refs, path):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    refs = _get_current_refs(request.user, repo, refs, True)
    if path is None or path == '':
        path = '.'
    gitHandler = GitHandler()
    abs_repopath = repo.get_abs_repopath()
    commit_hash = gitHandler.get_commit_hash(repo, abs_repopath, refs)
    commits = gitHandler.repo_log_file(abs_repopath, '0000000', commit_hash, 50, path)
    _fillwith_commits(commits)
    response_dictionary = {'mainnav': 'repo', 'current': 'commits', 'path': path, 'commits': commits}
    response_dictionary.update(get_common_repo_dict(request, repo, user_name, repo_name, refs))
    return render_to_response('repo/commits.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

@repo_permission_check
def commits_log(request, user_name, repo_name, from_commit_hash, to_commit_hash):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    gitHandler = GitHandler()
    abs_repopath = repo.get_abs_repopath()
    refs_meta = gitHandler.repo_ls_refs(repo, abs_repopath)

    orgi_from_commit_hash = from_commit_hash
    orgi_to_commit_hash = to_commit_hash
    from_commit_hash = gitHandler.get_commit_hash(repo, abs_repopath, from_commit_hash)
    to_commit_hash = gitHandler.get_commit_hash(repo, abs_repopath, to_commit_hash)
    commits = gitHandler.repo_log_file(abs_repopath, from_commit_hash, to_commit_hash, 50, '.')
    _fillwith_commits(commits)
    response_dictionary = {'mainnav': 'repo', 'current': 'commits', 'orgi_from_commit_hash': orgi_from_commit_hash, 'orgi_to_commit_hash': orgi_to_commit_hash, 'from_commit_hash': from_commit_hash, 'to_commit_hash': to_commit_hash, 'commits': commits, 'refs_meta': refs_meta}
    return json_httpResponse(response_dictionary)

@repo_permission_check
def branches_default(request, user_name, repo_name):
    return branches(request, user_name, repo_name, None)

@repo_permission_check
def branches(request, user_name, repo_name, refs):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    refs = _get_current_refs(request.user, repo, refs, True)
    response_dictionary = {'mainnav': 'repo', 'current': 'branches'}
    response_dictionary.update(get_common_repo_dict(request, repo, user_name, repo_name, refs))
    return render_to_response('repo/branches.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

@repo_permission_check
def tags_default(request, user_name, repo_name):
    return tags(request, user_name, repo_name, None)

@repo_permission_check
def tags(request, user_name, repo_name, refs):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    refs = _get_current_refs(request.user, repo, refs, True)
    response_dictionary = {'mainnav': 'repo', 'current': 'tags'}
    response_dictionary.update(get_common_repo_dict(request, repo, user_name, repo_name, refs))
    return render_to_response('repo/tags.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

@repo_permission_check
def compare_default(request, user_name, repo_name):
    return compare_master(request, user_name, repo_name, 'master')

@repo_permission_check
def compare_master(request, user_name, repo_name, refs):
    return compare_commit(request, user_name, repo_name, refs, 'master')

@repo_permission_check
def compare_commit(request, user_name, repo_name, from_refs, to_refs):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    refs = _get_current_refs(request.user, repo, None, True)
    gitHandler = GitHandler()
    abs_repopath = repo.get_abs_repopath()
    from_commit_hash = gitHandler.get_commit_hash(repo, abs_repopath, from_refs)
    to_commit_hash = gitHandler.get_commit_hash(repo, abs_repopath, to_refs)
    refs_meta = gitHandler.repo_ls_refs(repo, abs_repopath)
    response_dictionary = {'mainnav': 'repo', 'current': 'compare', 'from_refs': from_refs, 'to_refs': to_refs, 'from_commit_hash': from_commit_hash, 'to_commit_hash': to_commit_hash, 'refs_meta': refs_meta}
    response_dictionary.update(get_common_repo_dict(request, repo, user_name, repo_name, refs))
    return render_to_response('repo/compare.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

@repo_permission_check
@login_required
@require_http_methods(["POST"])
def merge(request, user_name, repo_name, source_refs, desc_refs):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None or not RepoManager.is_repo_member(repo, request.user):
        raise Http404
    merge_commit_message = 'Merge branch %s into %s, by %s' % (source_refs, desc_refs, '@' + str(request.user.username))
    if request.user.id != repo.user_id:
        merge_commit_message = merge_commit_message + ', @' + repo.username
    gitHandler = GitHandler()
    (returncode, output) = gitHandler.merge_pull_request(repo, repo, source_refs, desc_refs, merge_commit_message)
    merge_output_split = '----------- starting merge -----------'
    if merge_output_split in output:
        output = output.split(merge_output_split)[1].strip()
    RepoManager.delete_repo_commit_version(repo)
    return json_httpResponse({'source_refs': source_refs, 'desc_refs': desc_refs, 'returncode': returncode, 'output': output, 'result': 'success'})

@repo_permission_check
def pulls(request, user_name, repo_name):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    refs = _get_current_refs(request.user, repo, None, True); path = '.'
    pullRequests = RepoManager.list_pullRequest_by_descRepoId(repo.id)
    response_dictionary = {'mainnav': 'repo', 'current': 'pull', 'path': path, 'pullRequests': pullRequests}
    response_dictionary.update(get_common_repo_dict(request, repo, user_name, repo_name, refs))
    return render_to_response('repo/pulls.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

@login_required
@repo_permission_check
def pull_new_default(request, user_name, repo_name):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    source_username = user_name
    source_refs = 'master'
    desc_username = user_name
    desc_refs = 'master'
    if user_name != request.user.username:
        child_repo = RepoManager.get_childrepo_by_user_forkrepo(request.user, repo)
        if child_repo is not None:
            source_username = child_repo.username
            source_refs = 'master'
    return pull_new(request, user_name, repo_name, source_username, source_refs, desc_username, desc_refs)

@login_required
@repo_permission_check
def pull_new(request, user_name, repo_name, source_username, source_refs, desc_username, desc_refs):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    source_repo = RepoManager.get_repo_by_forkrepo(source_username, repo)
    desc_repo = RepoManager.get_repo_by_forkrepo(desc_username, repo)
    if repo is None or source_repo is None or desc_repo is None:
        raise Http404
    refs = _get_current_refs(request.user, repo, None, True); path = '.'

    # pull action
    if request.method == 'POST':
        source_repo = request.POST.get('source_repo', '')
        source_refs = request.POST.get('source_refs', '')
        desc_repo = request.POST.get('desc_repo', '')
        desc_refs = request.POST.get('desc_refs', '')
        title = request.POST.get('title', '')
        desc = request.POST.get('desc', '')
        if source_repo == '' or source_refs == '' or desc_repo == '' or desc_refs == '' or title == '' or '/' not in source_repo or '/' not in desc_repo:
            return pull_new(request, user_name, repo_name, source_username, source_refs, desc_username, desc_refs)
        if not RepoManager.is_allowed_refsname_pattern(source_refs) or not RepoManager.is_allowed_refsname_pattern(desc_refs):
            return pull_new(request, user_name, repo_name, source_username, source_refs, desc_username, desc_refs)
        (source_username, source_reponame) = source_repo.split('/', 1)
        (desc_username, desc_reponame) = desc_repo.split('/', 1)
        source_pull_repo = RepoManager.get_repo_by_name(source_username, source_reponame)
        desc_pull_repo = RepoManager.get_repo_by_name(desc_username, desc_reponame)
        if not _has_pull_right(request, source_pull_repo, desc_pull_repo):
            return pull_new(request, user_name, repo_name, source_username, source_refs, desc_username, desc_refs)
        pullRequest = PullRequest.create(request.user.id, desc_pull_repo.user_id, source_pull_repo.user_id, source_pull_repo.id, source_refs, desc_pull_repo.user_id, desc_pull_repo.id, desc_refs, title, desc, 0, PULL_STATUS.NEW)
        pullRequest.save()
        pullRequest.fillwith()
        FeedManager.notif_pull_request_status(pullRequest, pullRequest.status)
        FeedManager.notif_at(NOTIF_TYPE.AT_MERGE, request.user.id, pullRequest.id, pullRequest.title + ' ' + pullRequest.desc)
        FeedManager.feed_pull_change(pullRequest, pullRequest.status)
        return HttpResponseRedirect('/%s/%s/pulls/' % (desc_username, desc_reponame))

    pull_repo_list = _list_pull_repo(request, repo)
    response_dictionary = {'mainnav': 'repo', 'current': 'pull', 'path': path, 'source_username': source_username, 'source_refs': source_refs, 'desc_username': desc_username, 'desc_refs': desc_refs, 'source_repo': source_repo, 'desc_repo': desc_repo, 'pull_repo_list': pull_repo_list}
    response_dictionary.update(get_common_repo_dict(request, repo, user_name, repo_name, refs))
    return render_to_response('repo/pull_new.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

@repo_permission_check
def pull_show(request, user_name, repo_name, pullRequest_id):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    refs = _get_current_refs(request.user, repo, None, True); path = '.'
    pullRequest = RepoManager.get_pullRequest_by_repoId_id(repo.id, pullRequest_id)
    
    response_dictionary = {'mainnav': 'repo', 'current': 'pull', 'path': path, 'pullRequest': pullRequest}
    response_dictionary.update(get_common_repo_dict(request, repo, user_name, repo_name, refs))
    return render_to_response('repo/pull_show.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

@repo_permission_check
@require_http_methods(["POST"])
def pull_commits(request, user_name, repo_name, source_username, source_refs, desc_username, desc_refs):
    repo = RepoManager.get_repo_by_name(user_name, repo_name); path = '.'
    source_repo = RepoManager.get_repo_by_forkrepo(source_username, repo)
    desc_repo = RepoManager.get_repo_by_forkrepo(desc_username, repo)
    if repo is None or source_repo is None or desc_repo is None:
        return json_httpResponse({'commits': {}, 'result': 'failed'})
    if not _has_pull_right(request, source_repo, desc_repo):
        return json_httpResponse({'commits': {}, 'result': 'failed'})

    gitHandler = GitHandler()
    # prepare pullrequest
    gitHandler.prepare_pull_request(source_repo, desc_repo)
    pullrequest_repo_path = '%s/%s/%s' % (PULLREQUEST_REPO_PATH, desc_repo.username, desc_repo.name)

    source_repo_refs_commit_hash = gitHandler.get_commit_hash(source_repo, source_repo.get_abs_repopath(), source_refs)
    desc_repo_refs_commit_hash = gitHandler.get_commit_hash(desc_repo, desc_repo.get_abs_repopath(), desc_refs)
    commits = gitHandler.repo_log_file(pullrequest_repo_path, desc_repo_refs_commit_hash, source_repo_refs_commit_hash, 50, '.')
    _fillwith_commits(commits)
    return json_httpResponse({'commits': commits, 'source_refs': source_refs, 'desc_refs': desc_refs, 'source_repo_refs_commit_hash': source_repo_refs_commit_hash, 'desc_repo_refs_commit_hash': desc_repo_refs_commit_hash, 'result': 'success'})
    
@repo_permission_check
@require_http_methods(["POST"])
def pull_diff(request, user_name, repo_name, source_username, source_refs, desc_username, desc_refs, context):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    source_repo = RepoManager.get_repo_by_forkrepo(source_username, repo)
    desc_repo = RepoManager.get_repo_by_forkrepo(desc_username, repo)
    if repo is None or source_repo is None or desc_repo is None:
        return json_httpResponse({'diff': {}, 'result': 'failed'})
    refs = _get_current_refs(request.user, repo, None, True); path = '.'
    if not _has_pull_right(request, source_repo, desc_repo):
        return json_httpResponse({'diff': {}, 'result': 'failed'})

    gitHandler = GitHandler()
    # prepare pullrequest
    gitHandler.prepare_pull_request(source_repo, desc_repo)
    pullrequest_repo_path = '%s/%s/%s' % (PULLREQUEST_REPO_PATH, desc_repo.username, desc_repo.name)

    source_repo_refs_commit_hash = gitHandler.get_commit_hash(source_repo, source_repo.get_abs_repopath(), source_refs)
    desc_repo_refs_commit_hash = gitHandler.get_commit_hash(desc_repo, desc_repo.get_abs_repopath(), desc_refs)
    diff = gitHandler.repo_diff(pullrequest_repo_path, source_repo_refs_commit_hash, desc_repo_refs_commit_hash, context, '.')
    for x in diff['detail']:
        mode = x['mode']
        filename = x['filename']
        filetype = 'tree' if filename.endswith('/') else 'blob'
        fileusername = desc_repo.username
        filereponame = desc_repo.name
        filerefs = desc_refs
        if mode == 'delete':
            fileusername = source_repo.username
            filereponame = source_repo.name
            filerefs = source_refs
        filepath = '/%s/%s/%s/%s/%s' % (fileusername, filereponame, filetype, filerefs, filename)
        x['filepath'] = filepath
    return json_httpResponse({'user_name': user_name, 'repo_name': repo_name, 'path': path, 'source_username': source_username, 'source_refs': source_refs, 'desc_username': desc_username, 'desc_refs': desc_refs, 'diff': diff, 'source_repo_refs_commit_hash': source_repo_refs_commit_hash, 'desc_repo_refs_commit_hash': desc_repo_refs_commit_hash, 'result': 'success', 'context': context})

@repo_permission_check
@login_required
@require_http_methods(["POST"])
def pull_merge(request, user_name, repo_name, pullRequest_id):
    args = _get_repo_pull_args(user_name, repo_name, pullRequest_id)
    if args is None:
        return json_httpResponse({'returncode': 128, 'output': 'merge failed', 'result': 'failed'})
    (repo, pullRequest, source_repo, desc_repo, pullrequest_repo_path) = tuple(args)
    if not _has_pull_right(request, source_repo, desc_repo):
        return json_httpResponse({'result': 'failed'})
    if desc_repo is None or desc_repo.user_id != request.user.id:
        return json_httpResponse({'result': 'failed'})
    source_refs = pullRequest.source_refname
    desc_refs = pullRequest.desc_refname
    gitHandler = GitHandler()
    pullrequest_user = GsuserManager.get_user_by_id(pullRequest.pull_user_id)
    merge_commit_message = PULLREQUEST_COMMIT_MESSAGE_TMPL % (source_refs, source_repo.username, source_repo.name, desc_refs, desc_repo.username, desc_repo.name, pullRequest.id, '@' + str(pullrequest_user.username))
    (returncode, output) = gitHandler.merge_pull_request(source_repo, desc_repo, source_refs, desc_refs, merge_commit_message)
    pullRequest.status = PULL_STATUS.MERGED
    if returncode != 0:
        pullRequest.status = PULL_STATUS.MERGED_FAILED
    pullRequest.save()
    FeedManager.notif_pull_request_status(pullRequest, pullRequest.status)
    FeedManager.feed_pull_change(pullRequest, pullRequest.status)
    merge_output_split = '----------- starting merge -----------'
    if merge_output_split in output:
        output = output.split(merge_output_split)[1].strip()
    RepoManager.delete_repo_commit_version(repo)
    return json_httpResponse({'returncode': returncode, 'output': output, 'result': 'success'})

@repo_permission_check
@login_required
@require_http_methods(["POST"])
def pull_reject(request, user_name, repo_name, pullRequest_id):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None or repo.user_id != request.user.id:
        return json_httpResponse({'result': 'failed'})
    pullRequest = RepoManager.get_pullRequest_by_repoId_id(repo.id, pullRequest_id)
    if pullRequest is None:
        return json_httpResponse({'result': 'failed'})
    pullRequest.status = PULL_STATUS.REJECTED
    pullRequest.save()
    FeedManager.notif_pull_request_status(pullRequest, pullRequest.status)
    FeedManager.feed_pull_change(pullRequest, pullRequest.status)
    return json_httpResponse({'result': 'success'})

@repo_permission_check
@login_required
@require_http_methods(["POST"])
def pull_close(request, user_name, repo_name, pullRequest_id):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None or repo.user_id != request.user.id:
        return json_httpResponse({'result': 'failed'})
    pullRequest = RepoManager.get_pullRequest_by_repoId_id(repo.id, pullRequest_id)
    if pullRequest is None:
        return json_httpResponse({'result': 'failed'})
    pullRequest.status = PULL_STATUS.CLOSE
    pullRequest.save()
    FeedManager.notif_pull_request_status(pullRequest, pullRequest.status)
    FeedManager.feed_pull_change(pullRequest, pullRequest.status)
    return json_httpResponse({'result': 'success'})

def _get_repo_pull_args(user_name, repo_name, pullRequest_id):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        return None
    pullRequest = RepoManager.get_pullRequest_by_repoId_id(repo.id, pullRequest_id)
    if pullRequest is None:
        return None
    source_repo = RepoManager.get_repo_by_id(pullRequest.source_repo_id)
    desc_repo = RepoManager.get_repo_by_id(pullRequest.desc_repo_id)
    if source_repo is None or desc_repo is None:
        return None
    pullrequest_repo_path = '%s/%s/%s' % (PULLREQUEST_REPO_PATH, desc_repo.username, desc_repo.name)
    return [repo, pullRequest, source_repo, desc_repo, pullrequest_repo_path]
    
@repo_permission_check
@require_http_methods(["POST"])
def diff_default(request, user_name, repo_name, pre_commit_hash, commit_hash, context):
    return diff(request, user_name, repo_name, pre_commit_hash, commit_hash, context, '.')

@repo_permission_check
@require_http_methods(["POST"])
def diff(request, user_name, repo_name, from_commit_hash, to_commit_hash, context, path):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    if path is None or path == '':
        path = '.'
    diff = u'+++没有源代码、二进制文件，或者没有查看源代码权限，半公开和私有项目需要申请成为成员才能查看源代码'
    gitHandler = GitHandler()
    abs_repopath = repo.get_abs_repopath()
    refs_meta = gitHandler.repo_ls_refs(repo, abs_repopath)

    orgi_from_commit_hash = from_commit_hash
    orgi_to_commit_hash = to_commit_hash
    from_commit_hash = gitHandler.get_commit_hash(repo, abs_repopath, from_commit_hash)
    to_commit_hash = gitHandler.get_commit_hash(repo, abs_repopath, to_commit_hash)
    if repo.auth_type == 0 or RepoManager.is_repo_member(repo, request.user):
        diff = gitHandler.repo_diff(abs_repopath, from_commit_hash, to_commit_hash, context, path)
        for x in diff['detail']:
            mode = x['mode']
            filename = x['filename']
            filetype = 'tree' if filename.endswith('/') else 'blob'
            filerefs = orgi_to_commit_hash
            if mode == 'delete':
                filerefs = orgi_from_commit_hash
            filepath = '/%s/%s/%s/%s/%s' % (user_name, repo_name, filetype, filerefs, filename)
            x['filepath'] = filepath
    diff['orgi_from_commit_hash'] = orgi_from_commit_hash
    diff['orgi_to_commit_hash'] = orgi_to_commit_hash
    diff['from_commit_hash'] = from_commit_hash
    diff['to_commit_hash'] = to_commit_hash
    diff['refs_meta'] = refs_meta
    return json_httpResponse({'user_name': user_name, 'repo_name': repo_name, 'path': path, 'diff': diff})

@repo_permission_check
def collaborator(request, user_name, repo_name):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    refs = _get_current_refs(request.user, repo, None, True); path = '.'; current = 'collaborator'
    error = u''
    repoMemberForm = RepoMemberForm()
    if request.method == 'POST' and request.user.is_authenticated():
        repoMemberForm = RepoMemberForm(request.POST)
        if repoMemberForm.is_valid():
            username = repoMemberForm.cleaned_data['username'].strip()
            action = repoMemberForm.cleaned_data['action']
            if action == 'add_member':
                length = len(RepoManager.list_repomember(repo.id))
                if length < 10:
                    RepoManager.add_member(repo.id, username)
                else:
                    error = u'成员数目不得超过10位'
            if action == 'remove_member':
                RepoManager.remove_member(repo.id, username)
    user_id = request.user.id
    member_ids = [o.user_id for o in RepoManager.list_repomember(repo.id)]
    member_ids.insert(0, repo.user_id)
    if user_id != repo.user_id and user_id in member_ids:
        member_ids.remove(user_id)
        member_ids.insert(0, user_id)
    merge_user_map = GsuserManager.map_users(member_ids)
    members_vo = [merge_user_map[o] for o in member_ids]
    response_dictionary = {'mainnav': 'repo', 'current': current, 'path': path, 'members_vo': members_vo, 'repoMemberForm': repoMemberForm}
    response_dictionary.update(get_common_repo_dict(request, repo, user_name, repo_name, refs))
    return render_to_response('repo/collaborator.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

@repo_permission_check
def pulse(request, user_name, repo_name):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    refs = _get_current_refs(request.user, repo, None, True); path = '.'; current = 'pulse'
    raw_fork_repos_tree = []
    fork_repo_id = repo.fork_repo_id
    if fork_repo_id != 0:
        fork_repo = RepoManager.get_repo_by_id(fork_repo_id)
        if fork_repo is not None:
            raw_fork_repos_tree.append([fork_repo])
    else:
        raw_fork_repos_tree.append([])
    raw_fork_repos_tree.append([repo])
    fork_me_repos = RepoManager.list_fork_repo(repo.id)
    raw_fork_repos_tree.append(fork_me_repos)
    fork_repos_tree = change_to_vo(raw_fork_repos_tree)
    star_users = RepoManager.list_star_user(repo.id, 0, 20)
    watch_users = RepoManager.list_watch_user(repo.id)
    response_dictionary = {'mainnav': 'repo', 'current': current, 'path': path, 'fork_repos_tree': fork_repos_tree, 'star_users': star_users, 'watch_users': watch_users}
    response_dictionary.update(get_common_repo_dict(request, repo, user_name, repo_name, refs))
    return render_to_response('repo/pulse.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

@repo_permission_check
def stats(request, user_name, repo_name):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    refs = _get_current_refs(request.user, repo, None, True); path = '.'; current = 'stats'
    userprofile = GsuserManager.get_userprofile_by_id(repo.user_id)
    now = datetime.now()
    last12hours = timeutils.getlast12hours(now)
    last7days = timeutils.getlast7days(now)
    last30days = timeutils.getlast30days(now)
    last12months = timeutils.getlast12months(now)
    raw_last12hours_commit = StatsManager.list_repo_stats(repo.id, 'hour', datetime.fromtimestamp(last12hours[-1]), datetime.fromtimestamp(last12hours[0]))
    last12hours_commit = dict([(time.mktime(x.date.timetuple()), int(x.count)) for x in raw_last12hours_commit])
    raw_last30days_commit = StatsManager.list_repo_stats(repo.id, 'day', datetime.fromtimestamp(last30days[-1]), datetime.fromtimestamp(last30days[0]))
    last30days_commit = dict([(time.mktime(x.date.timetuple()), int(x.count)) for x in raw_last30days_commit])
    last7days_commit = {}
    for x in last7days:
        if x in last30days_commit:
            last7days_commit[x] = last30days_commit[x]
    raw_last12months_commit = StatsManager.list_repo_stats(repo.id, 'month', datetime.fromtimestamp(last12months[-1]), datetime.fromtimestamp(last12months[0]))
    last12months_commit = dict([(time.mktime(x.date.timetuple()), int(x.count)) for x in raw_last12months_commit])

    round_week = timeutils.get_round_week(now)
    round_month = timeutils.get_round_month(now)
    round_year = timeutils.get_round_year(now)

    raw_per_last_week_commits = StatsManager.list_repo_user_stats(repo.id, 'week', round_week)
    raw_per_last_month_commits = StatsManager.list_repo_user_stats(repo.id, 'month', round_month)
    raw_per_last_year_commits = StatsManager.list_repo_user_stats(repo.id, 'year', round_year)

    raw_week_user_ids = [x.user_id for x in raw_per_last_week_commits]
    raw_month_user_ids = [x.user_id for x in raw_per_last_month_commits]
    raw_year_user_ids = [x.user_id for x in raw_per_last_year_commits]
    uniq_user_ids = list(set(raw_week_user_ids + raw_month_user_ids + raw_year_user_ids))
    user_dict = GsuserManager.map_users(uniq_user_ids)

    per_user_week_commits = _list_user_count_dict(raw_per_last_week_commits, user_dict)
    per_user_month_commits = _list_user_count_dict(raw_per_last_month_commits, user_dict)
    per_user_year_commits = _list_user_count_dict(raw_per_last_year_commits, user_dict)
    round_week_tip = u'%s 以来贡献者' % round_week.strftime('%y/%m/%d')
    round_month_tip = u'%s 以来贡献者' %  round_month.strftime('%y/%m/%d')
    round_year_tip = u'%s 以来贡献者' %  round_year.strftime('%y/%m/%d')
    per_user_commits = []
    if len(per_user_week_commits) > 0:
        per_user_commits.append({'commits': per_user_week_commits, 'tip': round_week_tip})
    if len(per_user_month_commits) > 0:
        per_user_commits.append({'commits': per_user_month_commits, 'tip': round_month_tip})
    if len(per_user_year_commits) > 0:
        per_user_commits.append({'commits': per_user_year_commits, 'tip': round_year_tip})

    quotes = {'used_quote': _get_readable_du(repo.used_quote), 'total_quote': _get_readable_du(userprofile.quote), 'ratio': int(repo.used_quote)*100/int(userprofile.quote)}
    response_dictionary = {'mainnav': 'repo', 'current': 'stats', 'path': path, 'last12hours': last12hours, 'last7days': last7days, 'last30days': last30days, 'last12months': last12months, 'last12hours_commit': last12hours_commit, 'last7days_commit': last7days_commit, 'last30days_commit': last30days_commit, 'last12months_commit': last12months_commit, 'quotes': quotes, 'round_week': round_week, 'round_month': round_month, 'round_year': round_year, 'per_user_commits': per_user_commits}
    response_dictionary.update(get_common_repo_dict(request, repo, user_name, repo_name, refs))
    return render_to_response('repo/stats.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

@repo_permission_check
@login_required
def settings(request, user_name, repo_name):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    if repo.user_id != request.user.id and not TeamManager.get_teamMember_by_userId_teamUserId(request.user.id, repo.user_id):
        raise Http404
    refs = _get_current_refs(request.user, repo, None, True); path = '.'; current = 'settings'; error = u''
    repoForm = RepoForm(instance = repo)
    response_dictionary = {'mainnav': 'repo', 'current': current, 'path': path, 'repoForm': repoForm, 'error': error}
    if request.method == 'POST':
        repoForm = RepoForm(request.POST, instance = repo)
        if not repoForm.is_valid():
            error = u'输入正确的仓库名称[a-zA-Z0-9_-]，不能 - 开头，选择好语言和可见度，active、watch、recommend、repo是保留的名称。'
            return __response_edit_repo_error(request, response_dictionary, error)
        name = repoForm.cleaned_data['name']
        if not RepoManager.is_allowed_reponame_pattern(name):
            error = u'输入正确的仓库名称[a-zA-Z0-9_-]，不能 - 开头，active、watch、recommend、repo是保留的名称。'
            return __response_edit_repo_error(request, response_dictionary, error)
        repo = repoForm.save()
        RepoManager.check_export_ok_file(repo)
        return HttpResponseRedirect('/%s/%s/' % (repo.username, repo.name))

    if repo.dropbox_sync == 1 and (repo.dropbox_url is None or repo.dropbox_url == ''):
        dropbox_url = dropbox_share_direct('repositories/%s/%s_%s.git' % (repo.username, repo.id, repo.name))
        if dropbox_url is not None and dropbox_url != '':
            repo.dropbox_url = dropbox_url
            repo.save()
    response_dictionary.update(get_common_repo_dict(request, repo, user_name, repo_name, refs))
    return render_to_response('repo/settings.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

@repo_permission_check
@login_required
@require_http_methods(["POST"])
def generate_deploy_url(request, user_name, repo_name):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None or repo.user_id != request.user.id:
        return json_httpResponse({'result': 'failed'})
    random_hash = '%032x' % random.getrandbits(128)
    repo.deploy_url = random_hash
    repo.save()
    return json_httpResponse({'result': 'success'})

@repo_permission_check
@login_required
@require_http_methods(["POST"])
def forbid_dploy_url(request, user_name, repo_name):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None or repo.user_id != request.user.id:
        return json_httpResponse({'result': 'failed'})
    repo.deploy_url = ''
    repo.save()
    return json_httpResponse({'result': 'success'})

@repo_permission_check
@login_required
@require_http_methods(["POST"])
def enable_dropbox_sync(request, user_name, repo_name):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None or repo.user_id != request.user.id:
        return json_httpResponse({'result': 'failed'})
    repo.dropbox_sync = 1
    repo.last_push_time = datetime.now()
    if repo.dropbox_url is None or repo.dropbox_url == '':
        dropbox_url = dropbox_share_direct('repositories/%s/%s_%s.git' % (repo.username, repo.id, repo.name))
        repo.dropbox_url = dropbox_url
    repo.save()
    return json_httpResponse({'result': 'success'})

@repo_permission_check
@login_required
@require_http_methods(["POST"])
def disable_dropbox_sync(request, user_name, repo_name):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None or repo.user_id != request.user.id:
        return json_httpResponse({'result': 'failed'})
    repo.dropbox_sync = 0
    repo.last_push_time = datetime.now()
    repo.save()
    return json_httpResponse({'result': 'success'})

def list_latest_push_repo(request, last_push_time_str):
    secret_key = request.GET.get('secret_key')
    if secret_key != SECRET_KEY:
        return json_httpResponse({'result': 'failed'})
    timedelta_value = 0
    if re.match('\d+[sMdwmy]', last_push_time_str):
        timedelta_value = int(last_push_time_str[0:-1])
    if last_push_time_str.endswith('s'):
        push_timedelta = timedelta(seconds=-timedelta_value)
    elif last_push_time_str.endswith('M'):
        push_timedelta = timedelta(minutes=-timedelta_value)
    elif last_push_time_str.endswith('d'):
        push_timedelta = timedelta(days=-timedelta_value)
    elif last_push_time_str.endswith('w'):
        push_timedelta = timedelta(weeks=-timedelta_value)
    elif last_push_time_str.endswith('m'):
        push_timedelta = timedelta(days=-timedelta_value*30)
    elif last_push_time_str.endswith('y'):
        push_timedelta = timedelta(days=-timedelta_value*365)
    last_push_time = datetime.now() + push_timedelta
    repos = RepoManager.list_repo_by_last_push_time(last_push_time)
    repos_as_view = []
    for repo in repos:
        repo_as_view = {}
        repo_as_view['id'] = repo.id
        repo_as_view['username'] = repo.username
        repo_as_view['name'] = repo.name
        repo_as_view['dropbox_sync'] = repo.dropbox_sync
        repo_as_view['visibly'] = repo.visibly
        repos_as_view.append(repo_as_view)
    return json_httpResponse({'result': 'success', 'latest_push_repos': repos_as_view})

def change_to_vo(raw_fork_repos_tree):
    user_ids = []
    for raw_fork_repos in raw_fork_repos_tree:
        for raw_fork_repo in raw_fork_repos:
            user_ids.append(raw_fork_repo.user_id)
    fork_repos_tree = []
    user_map = GsuserManager.map_users(user_ids)
    for raw_fork_repos in raw_fork_repos_tree:
        fork_repos_tree.append(_conver_repos(raw_fork_repos, user_map))
    return fork_repos_tree

@repo_permission_check
@require_http_methods(["POST"])
def log_graph(request, user_name, repo_name, refs):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    abs_repopath = repo.get_abs_repopath()
    gitHandler = GitHandler()
    refs_meta = gitHandler.repo_ls_refs(repo, abs_repopath)

    orgi_commit_hash = refs
    commit_hash = gitHandler.get_commit_hash(repo, abs_repopath, refs)
    log_graph = gitHandler.repo_log_graph(repo, abs_repopath, commit_hash)
    log_graph['orgi_commit_hash'] = orgi_commit_hash
    log_graph['commit_hash'] = commit_hash
    log_graph['refs_meta'] = refs_meta
    response_dictionary = {'user_name': user_name, 'repo_name': repo_name}
    response_dictionary.update(log_graph)
    return json_httpResponse(response_dictionary)
    
@repo_permission_check
def refs_graph_default(request, user_name, repo_name):
    refs = None
    return refs_graph(request, user_name, repo_name, refs)

@repo_permission_check
def refs_graph(request, user_name, repo_name, refs):
    current = 'refs_graph'
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    refs = _get_current_refs(request.user, repo, refs, True)
    response_dictionary = {'mainnav': 'repo', 'current': current}
    response_dictionary.update(get_common_repo_dict(request, repo, user_name, repo_name, refs))
    return render_to_response('repo/refs_graph.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

@repo_permission_check
def refs_create(request, user_name, repo_name, refs):
    current = 'branches'
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None or not RepoManager.is_repo_member(repo, request.user):
        raise Http404
    response_dictionary = {'mainnav': 'repo', 'current': current}
    response_dictionary.update(get_common_repo_dict(request, repo, user_name, repo_name, refs))
    return render_to_response('repo/refs_create.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

@repo_permission_check
@require_http_methods(["POST"])
def refs_branch_create(request, user_name, repo_name, branch, base_branch):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None or not RepoManager.is_repo_member(repo, request.user):
        return json_httpResponse({'returncode': 128, 'result': 'failed'})
    gitHandler = GitHandler()
    if gitHandler.create_branch(repo, branch, base_branch):
        return json_httpResponse({'returncode': 0, 'result': 'success'})
    return json_httpResponse({'returncode': 128, 'result': 'failed'})

@repo_permission_check
@require_http_methods(["POST"])
def refs_branch_delete(request, user_name, repo_name, branch):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None or not RepoManager.is_repo_member(repo, request.user) or branch == 'master':
        return json_httpResponse({'returncode': 128, 'result': 'failed'})
    gitHandler = GitHandler()
    if gitHandler.delete_branch(repo, branch):
        return json_httpResponse({'returncode': 0, 'result': 'success'})
    return json_httpResponse({'returncode': 128, 'result': 'failed'})

@repo_permission_check
@require_http_methods(["POST"])
def refs_tag_create(request, user_name, repo_name, tag, base_branch):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None or not RepoManager.is_repo_member(repo, request.user):
        return json_httpResponse({'returncode': 128, 'result': 'failed'})
    gitHandler = GitHandler()
    if gitHandler.create_tag(repo, tag, base_branch):
        return json_httpResponse({'returncode': 0, 'result': 'success'})
    return json_httpResponse({'returncode': 128, 'result': 'failed'})

@repo_permission_check
@require_http_methods(["POST"])
def refs_tag_delete(request, user_name, repo_name, tag):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None or not RepoManager.is_repo_member(repo, request.user):
        return json_httpResponse({'returncode': 128, 'result': 'failed'})
    gitHandler = GitHandler()
    if gitHandler.delete_tag(repo, tag):
        return json_httpResponse({'returncode': 0, 'result': 'success'})
    return json_httpResponse({'returncode': 128, 'result': 'failed'})

@repo_permission_check
@require_http_methods(["POST"])
def refs(request, user_name, repo_name):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        return json_httpResponse({'user_name': user_name, 'repo_name': repo_name, 'branches': [], 'tags': []})
    repopath = repo.get_abs_repopath()

    gitHandler = GitHandler()
    refs_meta = gitHandler.repo_ls_refs(repo, repopath)
    response_dictionary = {'mainnav': 'repo', 'user_name': user_name, 'repo_name': repo_name, 'refs_meta': refs_meta}
    return json_httpResponse(response_dictionary)

@repo_permission_check
@login_required
@require_http_methods(["POST"])
def fork(request, user_name, repo_name):
    response_dictionary = {'mainnav': 'repo', 'user_name': user_name, 'repo_name': repo_name}
    has_error = False
    message = 'success'
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        message = u'仓库不存在'
        return json_httpResponse({'result': 'failed', 'message': message})
    userprofile = request.userprofile
    if (userprofile.pubrepo + userprofile.prirepo) >= 100:
        message = u'您的仓库总数量已经超过限制'
        has_error = True
    if (userprofile.used_quote + repo.used_quote) >= userprofile.quote:
        message = u'您剩余空间不足，总空间 %s kb，剩余 %s kb' % (userprofile.quote, userprofile.used_quote)
        has_error = True
    fork_repo = RepoManager.get_repo_by_name(request.user.username, repo.name);
    if fork_repo is not None:
        message = u'您已经有一个名字相同的仓库: %s' % (repo.name)
        has_error = True
    if has_error:
        return json_httpResponse({'result': 'failed', 'message': message})
    fork_repo = Repo.create(request.user.id, repo.id, request.user.username, repo.name, repo.desc, repo.lang, repo.auth_type, repo.used_quote)
    fork_repo.status = 1
    fork_repo.save()
    userprofile.used_quote = userprofile.used_quote + repo.used_quote
    userprofile.save()
    
    # fork event, clone...
    EventManager.send_fork_event(repo.id, fork_repo.id)
    response_dictionary.update({'result': 'success', 'message': 'fork done, start copy repo tree...'})
    return json_httpResponse(response_dictionary)

@repo_permission_check
@login_required
@require_http_methods(["POST"])
def watch(request, user_name, repo_name):
    response_dictionary = {'result': 'success'}
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        message = u'仓库不存在'
        return json_httpResponse({'result': 'failed', 'message': message})
    if not RepoManager.watch_repo(request.user, request.userprofile, repo):
        message = u'关注失败，关注数量超过限制或者仓库不允许关注'
        return json_httpResponse({'result': 'failed', 'message': message})
    return json_httpResponse(response_dictionary)

@repo_permission_check
@login_required
@require_http_methods(["POST"])
def unwatch(request, user_name, repo_name):
    response_dictionary = {'result': 'success'}
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        message = u'仓库不存在'
        return json_httpResponse({'result': 'failed', 'message': message})
    if not RepoManager.unwatch_repo(request.user, request.userprofile, repo):
        message = u'取消关注失败，可能仓库未被关注'
        return json_httpResponse({'result': 'failed', 'message': message})
    return json_httpResponse(response_dictionary)

@repo_permission_check
@login_required
@require_http_methods(["POST"])
def star(request, user_name, repo_name):
    response_dictionary = {'result': 'success'}
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        message = u'仓库不存在'
        return json_httpResponse({'result': 'failed', 'message': message})
    if not RepoManager.star_repo(request.user.id, repo.id):
        message = u'标星失败，标星数量超过限制或者仓库不允许标星'
        return json_httpResponse({'result': 'failed', 'message': message})
    return json_httpResponse(response_dictionary)

@repo_permission_check
@login_required
@require_http_methods(["POST"])
def unstar(request, user_name, repo_name):
    response_dictionary = {'result': 'success'}
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        message = u'仓库不存在'
        return json_httpResponse({'result': 'failed', 'message': message})
    if not RepoManager.unstar_repo(request.user.id, repo.id):
        message = u'取消标星失败，可能仓库未被标星'
        return json_httpResponse({'result': 'failed', 'message': message})
    return json_httpResponse(response_dictionary)

@login_required
def find(request):
    repo = None
    is_repo_exist = True
    name = request.POST.get('name')
    if RepoManager.is_allowed_reponame_pattern(name):
        repo = RepoManager.get_repo_by_name(request.user.username, name)
        is_repo_exist = (repo is not None)
    return json_httpResponse({'is_repo_exist': is_repo_exist, 'name': name})

@login_required
def create(request, user_name):
    error = u''
    if user_name != request.user.username:
        raise Http404
    thirdpartyUser = GsuserManager.get_thirdpartyUser_by_id(request.user.id)
    repo = Repo()
    repo.user_id = request.user.id
    repoForm = RepoForm(instance = repo)
    repoForm.fill_username(request.userprofile)
    response_dictionary = {'mainnav': 'repo', 'repoForm': repoForm, 'error': error, 'thirdpartyUser': thirdpartyUser, 'apply_error': request.GET.get('apply_error')}
    if request.method == 'POST':
        repoForm = RepoForm(request.POST, instance = repo)
        repoForm.fill_username(request.userprofile)
        userprofile = request.userprofile
        create_repo = repoForm.save(commit=False)
        username = create_repo.username
        if username != request.user.username:
            team_user = GsuserManager.get_user_by_name(username)
            if team_user:
                teamMember = TeamManager.get_teamMember_by_userId_teamUserId(request.user.id, team_user.id)
                if teamMember:
                    create_repo.user_id = team_user.id
                    create_repo.username = team_user.username
                    userprofile = GsuserManager.get_userprofile_by_id(team_user.id)
        if (userprofile.pubrepo + userprofile.prirepo) >= 100:
            error = u'拥有的仓库数量已经达到 100 的限制。'
            return __response_create_repo_error(request, response_dictionary, error)
        if not repoForm.is_valid():
            error = u'输入正确的仓库名称[a-zA-Z0-9_-]，不能 - 开头，选择好语言和可见度，active、watch、recommend、repo是保留的名称。'
            return __response_create_repo_error(request, response_dictionary, error)
        name = repoForm.cleaned_data['name']
        if not RepoManager.is_allowed_reponame_pattern(name):
            error = u'输入正确的仓库名称[a-zA-Z0-9_-]，不能 - 开头，active、watch、recommend、repo是保留的名称。'
            return __response_create_repo_error(request, response_dictionary, error)
        dest_repo = RepoManager.get_repo_by_userId_name(request.user.id, name)
        if dest_repo is not None:
            error = u'仓库名称已经存在。'
            return __response_create_repo_error(request, response_dictionary, error)
        if userprofile.used_quote > userprofile.quote:
            error = u'剩余空间不足，总空间 %s kb，剩余 %s kb' % (userprofile.quote, userprofile.used_quote)
            return __response_create_repo_error(request, response_dictionary, error)
        create_repo.save()
        userprofile.save()
        remote_git_url = request.POST.get('remote_git_url', '').strip()
        remote_username = request.POST.get('remote_username', '').strip()
        remote_password = request.POST.get('remote_password', '').strip()
        remote_git_url = __validate_get_remote_git_url(remote_git_url, remote_username, remote_password)
        if remote_git_url is not None and remote_git_url != '':
            create_repo.status = 2
            create_repo.save()
        fulfill_gitrepo(create_repo, remote_git_url)
        return HttpResponseRedirect('/%s/%s/' % (userprofile.username, name))
    return render_to_response('repo/create.html', response_dictionary, context_instance=RequestContext(request))

@login_required
#@require_http_methods(["POST"])
def recently(request, user_name):
    feedAction = FeedAction()
    _recently_view_repo = feedAction.list_recently_view_repo(request.user.id, 0, 10)
    recently_view_repo_ids = [int(x[0]) for x in _recently_view_repo]
    _recently_active_repo = feedAction.list_recently_active_repo(request.user.id, 0, 10)
    recently_active_repo_ids = [int(x[0]) for x in _recently_active_repo]
    unique_repo_ids = Set(recently_view_repo_ids + recently_active_repo_ids)
    repo_dict = dict([(x.id, x) for x in RepoManager.list_repo_by_ids(unique_repo_ids)])

    recently_view_repo = []
    recently_active_repo = []
    for x in recently_view_repo_ids:
        if x in repo_dict and repo_dict[x]:
            recently_view_repo.append(repo_dict[x])
        else:
            feedAction.remove_recently_view_repo(request.user.id, x)
    for x in recently_active_repo_ids:
        if x in repo_dict and repo_dict[x]:
            recently_active_repo.append(repo_dict[x])
        else:
            feedAction.remove_recently_active_repo(request.user.id, x)
    current_user = TeamManager.get_current_user(request.user, request.userprofile)
    recently_update_repo = RepoManager.list_repo_by_userId(current_user.id, 0, 5)
    return json_httpResponse({'result': 'success', 'cdoe': 200, 'message': 'recently view, active, update repo', 'recently_view_repo': recently_view_repo, 'recently_active_repo': recently_active_repo, 'recently_update_repo': recently_update_repo})

def __response_create_repo_error(request, response_dictionary, error):
    response_dictionary['error'] = error
    return render_to_response('repo/create.html', response_dictionary, context_instance=RequestContext(request))

def __validate_get_remote_git_url(remote_git_url, remote_username, remote_password):
    if remote_git_url != '' and not re.match('[a-zA-Z0-9_\.\-\/:]+', remote_git_url):
        return ''
    if remote_git_url.startswith('git://'):
        remote_git_url_as_http = 'http://' + remote_git_url[len('git://'):]
        if __is_url_valid(remote_git_url_as_http):
            return remote_git_url
        return ''
    if remote_username is None or remote_username == '':
        remote_username = 'remote_username'
    if remote_password is None or remote_password == '':
        remote_password = 'remote_password'
    remote_username = urllib.quote_plus(remote_username)
    remote_password = urllib.quote_plus(remote_password)
    if not __is_url_valid(remote_git_url):
        return ''
    protocol = ''
    remote_git_url_without_protocol = ''
    for protocol in ['http://', 'https://']:
        if remote_git_url.startswith(protocol):
            remote_git_url_without_protocol = remote_git_url[len(protocol):]
            return '%s%s:%s@%s' % (protocol, remote_username, remote_password, remote_git_url_without_protocol)
    return ''

def __is_url_valid(url):
    validator = URLValidator(verify_exists=False)
    try:
        validator(url)
        return True
    except ValidationError, e:
        logger.exception(e)
    return False
    
def __response_edit_repo_error(request, response_dictionary, error):
    response_dictionary['error'] = error
    return render_to_response('repo/edit.html', response_dictionary, context_instance=RequestContext(request))

@repo_permission_check
@login_required
def delete(request, user_name, repo_name):
    error = u''
    if user_name != request.user.username:
        raise Http404
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    gsuser = GsuserManager.get_userprofile_by_id(request.user.id)
    if request.method == 'POST':
        repo.visibly = 1
        repo.last_push_time = datetime.now()
        gsuser.used_quote = gsuser.used_quote - repo.used_quote
        if gsuser.used_quote < 0:
            gsuser.used_quote = 0
        gsuser.save()
        repo.save()
        delete_path = '%s/%s' % (DELETE_REPO_PATH, repo.id)
        abs_repopath = repo.get_abs_repopath()
        if os.path.exists(abs_repopath):
            shutil.move(abs_repopath, delete_path)
        feedAction = FeedAction()
        feedAction.delete_repo_feed(repo.id)
        return HttpResponseRedirect('/%s/-/repo/' % request.user.username)
    response_dictionary = {'mainnav': 'repo', 'user_name': user_name, 'repo_name': repo_name, 'error': error}
    return render_to_response('repo/delete.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

def get_commits_by_ids(ids):
    return RepoManager.get_commits_by_ids(ids)

def fulfill_gitrepo(repo, remote_git_url):
    gitHandler = GitHandler()
    username = repo.username
    reponame = repo.name
    user_repo_path = '%s/%s' % (REPO_PATH, username)
    if not os.path.exists(user_repo_path):
        os.makedirs(user_repo_path)
        os.chmod(user_repo_path, 0755)
    repo_path = ('%s/%s/%s.git' % (REPO_PATH, username, reponame))
    if not os.path.exists(repo_path):
        if remote_git_url is not None and remote_git_url != '':
            EventManager.send_import_repo_event(username, reponame, remote_git_url)
        else:
            shutil.copytree(GIT_BARE_REPO_PATH, repo_path)
            gitHandler.update_server_info(repo)
    repo = RepoManager.get_repo_by_name(username, reponame)
    RepoManager.check_export_ok_file(repo)

def get_common_repo_dict(request, repo, user_name, repo_name, refs):
    gitHandler = GitHandler()
    refs_meta = gitHandler.repo_ls_refs(repo, repo.get_abs_repopath())
    is_watched_repo = RepoManager.is_watched_repo(request.user.id, repo.id)
    is_stared_repo = RepoManager.is_stared_repo(request.user.id, repo.id)
    is_repo_member = RepoManager.is_repo_member(repo, request.user)
    is_owner = (repo.user_id == request.user.id)
    is_branch = (refs in refs_meta['branches'])
    is_tag = (refs in refs_meta['tags'])
    is_commit = (not is_branch and not is_tag)
    has_forked = False
    has_fork_right = (repo.auth_type == 0 or is_repo_member)
    has_pull_right = is_owner
    user_child_repo = None
    parent_repo = None
    if repo.fork_repo_id:
        parent_repo = RepoManager.get_repo_by_id(repo.fork_repo_id)
    if not is_owner:
        user_child_repo = RepoManager.get_childrepo_by_user_forkrepo(request.user, repo)
        if user_child_repo is not None:
            has_forked = True
            has_pull_right = True
    repo_pull_new_count = RepoManager.count_pullRequest_by_descRepoId(repo.id, PULL_STATUS.NEW)
    return { 'repo': repo, 'user_name': user_name, 'repo_name': repo_name, 'refs': refs, 'is_watched_repo': is_watched_repo, 'is_stared_repo': is_stared_repo, 'has_forked': has_forked, 'is_repo_member': is_repo_member, 'is_owner': is_owner, 'is_branch': is_branch, 'is_tag': is_tag, 'is_commit': is_commit, 'has_fork_right': has_fork_right, 'has_pull_right': has_pull_right, 'repo_pull_new_count': repo_pull_new_count, 'refs_meta': refs_meta, 'user_child_repo': user_child_repo, 'parent_repo': parent_repo}

@login_required
def list_github_repos(request):
    thirdpartyUser = GsuserManager.get_thirdpartyUser_by_id(request.user.id)
    if thirdpartyUser is None:
        return json_httpResponse({'result': 'failed', 'cdoe': 404, 'message': 'GitHub account not found', 'repos': []})
    access_token = thirdpartyUser.access_token
    repos_json_str = github_list_repo(access_token)
    return HttpResponse(repos_json_str, mimetype='application/json')

def _list_pull_repo(request, repo):
    raw_pull_repo_list = RepoManager.list_parent_repo(repo, 10)
    child_repo = RepoManager.get_childrepo_by_user_forkrepo(request.user, repo)
    if child_repo is not None:
        raw_pull_repo_list = [child_repo] + raw_pull_repo_list
    pull_repo_list = [x for x in raw_pull_repo_list if _has_repo_pull_right(request, x)]
    return pull_repo_list

def _has_repo_pull_right(request, repo):
    if repo is None:
        return False
    if repo.auth_type != 0 and not RepoManager.is_repo_member(repo, request.user):
        return False
    return True

def _has_pull_right(request, source_pull_repo, desc_pull_repo):
    if source_pull_repo is None or desc_pull_repo is None:
        return False
    if source_pull_repo.auth_type != 0 and not RepoManager.is_repo_member(source_pull_repo, request.user):
        return False
    if desc_pull_repo.auth_type != 0 and not RepoManager.is_repo_member(desc_pull_repo, request.user):
        return False
    return True

def _conver_repos(raw_repos, map_users):
    repos_vo = []
    for raw_repo in raw_repos:
        repo_dict = model_to_dict(raw_repo, fields=[field.name for field in Repo._meta.fields])
        repo_dict['id'] = raw_repo.id
        repo_dict['create_time'] = time.mktime(raw_repo.create_time.timetuple())
        repo_dict['modify_time'] = time.mktime(raw_repo.modify_time.timetuple())
        if raw_repo.user_id in map_users:
            repo_dict['username'] = map_users[raw_repo.user_id]['username']
            repo_dict['imgurl'] = map_users[raw_repo.user_id]['imgurl']
        repos_vo.append(repo_dict) 
    return repos_vo

def _fillwith_commits(commits):
    if not commits:
        return
    for commit in commits:
        userprofile = GsuserManager.get_userprofile_by_name(commit['author_name'])
        if userprofile:
            commit['author_imgurl'] = userprofile.imgurl
        else:
            commit['author_imgurl'] = '000000'

def _get_current_refs(user, repo, refs, update_to_cache):
    gitHandler = GitHandler()
    refs_meta = gitHandler.repo_ls_refs(repo, repo.get_abs_repopath())
    if refs and refs not in refs_meta['branches'] and refs not in refs_meta['tags']:
        return 'master'
    feedAction = FeedAction()
    repo_refs = feedAction.get_repo_attr(repo.id, AttrKey.REFS)
    if refs and RepoManager.is_allowed_refsname_pattern(refs):
        if refs != repo_refs and update_to_cache:
            feedAction.set_repo_attr(repo.id, AttrKey.REFS, refs)
        return refs
    if repo_refs:
        return repo_refs
    feedAction.set_repo_attr(repo.id, AttrKey.REFS, 'master')
    return 'master'

def _list_user_count_dict(raw_per_commit, user_dict):
    per_commits = []
    total_count = 0
    for x in raw_per_commit:
        user_id = x.user_id
        if user_id not in user_dict:
            continue
        total_count = total_count + int(x.count)
        per_commits.append({'name': user_dict[user_id]['username'], 'count': int(x.count)})
    for x in per_commits:
        ratio = x['count']*100/total_count
        if ratio == 0:
            ratio = 1
        x['ratio'] = ratio
    return per_commits

def _get_readable_du(quote):
    if quote < 1024:
        return str(quote) + 'b'
    if quote < 1048576:
        return str(quote/1024) + 'kb'
    if quote < 1073741824:
        return str(quote/1048576) + 'mb'
    return str(quote/1073741824) + 'g'

def json_ok():
    return json_httpResponse({'result': 'ok'})

def json_failed():
    return json_httpResponse({'result': 'failed'})


