# -*- coding: utf-8 -*-  
import os, re
import shutil
import json, time
from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.template import RequestContext
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import render_to_response
from django.utils.html import escape
from gitshell.feed.feed import FeedAction
from gitshell.repo.Forms import RepoForm, RepoIssuesForm, IssuesComment, RepoIssuesCommentForm, RepoMemberForm
from gitshell.repo.githandler import GitHandler
from gitshell.repo.models import Repo, RepoManager, Issues
from gitshell.repo.cons import TRACKERS, STATUSES, PRIORITIES, ISSUES_ATTRS, conver_issues, conver_issue_comments, conver_repos
from gitshell.gsuser.models import UserprofileManager
from gitshell.settings import PRIVATE_REPO_PATH, PUBLIC_REPO_PATH, GIT_BARE_REPO_PATH

@login_required
def user_repo(request, user_name):
    return user_repo_paging(request, user_name, 0)

@login_required
def user_repo_paging(request, user_name, pagenum):
    repo_list = RepoManager.list_repo_by_userId(request.user.id, 0, 25)
    repo_commit_map = {}
    feedAction = FeedAction()
    for repo in repo_list:
        repo_commit_map[str(repo.name)] = []
        feeds = feedAction.get_repo_feeds(repo.id, 0, 4)
        for feed in feeds:
            repo_commit_map[str(repo.name)].append(feed[0])
    response_dictionary = {'user_name': user_name, 'repo_list': repo_list, 'repo_commit_map': repo_commit_map}
    return render_to_response('repo/user_repo.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

def repo(request, user_name, repo_name):
    refs = 'master'; path = '.'; current = 'index'
    return repo_ls_tree(request, user_name, repo_name, refs, path, current)

def repo_default_tree(request, user_name, repo_name):
    refs = 'master'; path = '.'; current = 'tree'
    return repo_ls_tree(request, user_name, repo_name, refs, path, current)
    
def repo_tree(request, user_name, repo_name, refs, path):
    current = 'tree'
    return repo_ls_tree(request, user_name, repo_name, refs, path, current)

def repo_raw_tree(request, user_name, repo_name, refs, path):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None or path.endswith('/'):
        raise Http404
    gitHandler = GitHandler()
    abs_repopath = repo.get_abs_repopath(user_name)
    commit_hash = gitHandler.get_commit_hash(abs_repopath, refs)
    blob = gitHandler.repo_cat_file(abs_repopath, commit_hash, path)
    return HttpResponse(blob, content_type="text/plain")

lang_suffix = {'applescript': 'AppleScript', 'as3': 'AS3', 'bash': 'Bash', 'sh': 'Bash', 'cfm': 'ColdFusion', 'cfc': 'ColdFusion', 'cpp': 'Cpp', 'cxx': 'Cpp', 'c': 'Cpp', 'h': 'Cpp', 'cs': 'CSharp', 'css': 'Css', 'dpr': 'Delphi', 'dfm': 'Delphi', 'pas': 'Delphi', 'diff': 'Diff', 'patch': 'Diff', 'erl': 'Erlang', 'groovy': 'Groovy', 'fx': 'JavaFX', 'jfx': 'JavaFX', 'java': 'Java', 'js': 'JScript', 'pl': 'Perl', 'py': 'Python', 'php': 'Php', 'psl': 'PowerShell', 'rb': 'Ruby', 'sass': 'Sass', 'scala': 'Scala', 'sql': 'Sql', 'vb': 'Vb', 'xml': 'Xml', 'xhtml': 'Xml', 'html': 'Xml', 'htm': 'Xml'}
brush_aliases = {'AppleScript': 'applescript', 'AS3': 'actionscript3', 'Bash': 'shell', 'ColdFusion': 'coldfusion', 'Cpp': 'cpp', 'CSharp': 'csharp', 'Css': 'css', 'Delphi': 'delphi', 'Diff': 'diff', 'Erlang': 'erlang', 'Groovy': 'groovy', 'JavaFX': 'javafx', 'Java': 'java', 'JScript': 'javascript', 'Perl': 'perl', 'Php': 'php', 'Plain': 'plain', 'PowerShell': 'powershell', 'Python': 'python', 'Ruby': 'ruby', 'Sass': 'sass', 'Scala': 'scala', 'Sql': 'sql', 'Vb': 'vb', 'Xml': 'xml'}
def repo_ls_tree(request, user_name, repo_name, refs, path, current):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    if path is None or path == '':
        path = '.'
    gitHandler = GitHandler()
    abs_repopath = repo.get_abs_repopath(user_name)
    commit_hash = gitHandler.get_commit_hash(abs_repopath, refs)
    is_tree = True ; tree = {} ; blob = ''; lang = 'Plain'; brush = 'plain'
    if path == '.' or path.endswith('/'):
        tree = gitHandler.repo_ls_tree(abs_repopath, commit_hash, path)
    else:
        is_tree = False
        paths = path.split('.')
        if len(paths) > 0:
            suffix = paths[-1]
            if suffix in lang_suffix and lang_suffix[suffix] in brush_aliases:
                lang = lang_suffix[suffix]
                brush = brush_aliases[lang]
        blob = gitHandler.repo_cat_file(abs_repopath, commit_hash, path)
    response_dictionary = {'current': current, 'repo': repo, 'user_name': user_name, 'repo_name': repo_name, 'refs': refs, 'path': path, 'tree': tree, 'blob': blob, 'is_tree': is_tree, 'lang': lang, 'brush': brush}
    return render_to_response('repo/tree.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

def repo_default_commits(request, user_name, repo_name):
    refs = 'master'; path = '.'
    return repo_commits(request, user_name, repo_name, refs, path)
    
def repo_commits(request, user_name, repo_name, refs, path):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    if path is None or path == '':
        path = '.'
    gitHandler = GitHandler()
    abs_repopath = repo.get_abs_repopath(user_name)
    commit_hash = gitHandler.get_commit_hash(abs_repopath, refs)
    commits = gitHandler.repo_log_file(abs_repopath, commit_hash, path)
    response_dictionary = {'current': 'commits', 'repo': repo, 'user_name': user_name, 'repo_name': repo_name, 'refs': refs, 'path': path, 'commits': commits}
    return render_to_response('repo/commits.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

def repo_diff(request, user_name, repo_name, pre_commit_hash, commit_hash, path):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    if path is None or path == '':
        path = '.'
    gitHandler = GitHandler()
    abs_repopath = repo.get_abs_repopath(user_name)
    diff = gitHandler.repo_diff(abs_repopath, pre_commit_hash, commit_hash, path)
    return HttpResponse(json.dumps({'diff': escape(diff)}), mimetype="application/json")

def issues(request, user_name, repo_name):
    return issues_list(request, user_name, repo_name, None, TRACKERS[0].value, STATUSES[0].value, PRIORITIES[0].value, 'modify_time', 0)
 
def issues_list(request, user_name, repo_name, assigned, tracker, status, priority, orderby, page):
    refs = 'master'; path = '.'; current = 'issues'
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    user_id = request.user.id
    member_ids = [o.user_id for o in RepoManager.list_repomember(repo.id)]
    member_ids.insert(0, repo.user_id)
    if user_id != repo.user_id and user_id in member_ids:
        member_ids.remove(user_id)
        member_ids.insert(0, user_id)
    members = UserprofileManager.list_user_by_ids(member_ids)
    assigneds = [o.username for o in members]
    if assigned is None:
        assigned = assigneds[0]
    assigned_id = repo.user_id
    assigned_user = UserprofileManager.get_user_by_name(assigned)
    if assigned_user is not None and assigned in assigneds:
        assigned_id = assigned_user.id
    tracker = int(tracker); status = int(status); priority = int(priority); page = int(page)
    current_attrs = { "assigned": str(assigned), "tracker": tracker, "status": status, "priority": priority, "orderby": str(orderby), "page": page }
    raw_issues = RepoManager.list_issues(repo.id, assigned_id, tracker, status, priority, orderby, page)
    reporter_ids = [o.user_id for o in raw_issues]
    reporters = UserprofileManager.list_user_by_ids(list(set(reporter_ids)-set(member_ids)))
    user_map = {}
    for member in members:
        user_map[member.id] = member.username
    for reporter in reporters:
        user_map[reporter.id] = reporter.username
    issues = conver_issues(raw_issues, user_map)

    hasPre = False ; hasNext = False
    if page > 0:
        hasPre = True 
    if len(issues) > 2:
        hasNext = True
        issues.pop()
    
    response_dictionary = {'current': current, 'user_name': user_name, 'repo_name': repo_name, 'refs': refs, 'path': path, 'assigneds': assigneds, 'assigned': assigned, 'tracker': tracker, 'status': status, 'priority': priority, 'orderby': orderby, 'page': page, 'current_attrs': current_attrs, 'issues': issues, 'hasPre': hasPre, 'hasNext': hasNext}
    response_dictionary.update(ISSUES_ATTRS)
    return render_to_response('repo/issues.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

def issues_default_show(request, user_name, repo_name, issues_id):
    return issues_show(request, user_name, repo_name, issues_id, None)

def issues_show(request, user_name, repo_name, issues_id, page):
    refs = 'master'; path = '.'; current = 'issues'
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    raw_issue = RepoManager.get_issues(repo.id, issues_id)
    if raw_issue is None:
        raise Http404
    repoIssuesCommentForm = RepoIssuesCommentForm()
    if request.method == 'POST':
        issuesComment = IssuesComment() 
        issuesComment.issues_id = issues_id
        issuesComment.user_id = request.user.id
        repoIssuesCommentForm = RepoIssuesCommentForm(request.POST, instance = issuesComment)
        if repoIssuesCommentForm.is_valid():
            repoIssuesCommentForm.save()
            raw_issue.comment_count = raw_issue.comment_count + 1
            raw_issue.save()
            return HttpResponseRedirect('/%s/%s/issues/%s/' % (user_name, repo_name, issues_id))
    issues_id = int(issues_id)
    user_map = {}
    users = UserprofileManager.list_user_by_ids([raw_issue.user_id, raw_issue.assigned])
    for user in users:
        user_map[user.id] = user.username
    issue = conver_issues([raw_issue], user_map)[0]
    
    total_page = issue['comment_count'] / 2
    if issue['comment_count'] != 0 and issue['comment_count'] % 2 == 0:
        total_page = total_page - 1
    if page is None or int(page) > total_page:
        page = total_page
    else:
        page = int(page)
    user_map = {}
    user_img_map = {}
    issue_comments = []
    if issue['comment_count'] > 0:
        raw_issue_comments = RepoManager.list_issues_comment(issues_id, page)
        user_ids = [o.user_id for o in raw_issue_comments]
        users = UserprofileManager.list_user_by_ids(user_ids)
        userprofiles = UserprofileManager.list_userprofile_by_ids(user_ids)
        for user in users:
            user_map[user.id] = user.username
        for userprofile in userprofiles:
            user_img_map[userprofile.id] = userprofile.imgurl 
        issue_comments = conver_issue_comments(RepoManager.list_issues_comment(issues_id, page), user_map, user_img_map)
    response_dictionary = {'current': current, 'user_name': user_name, 'repo_name': repo_name, 'refs': refs, 'path': path, 'issue': issue, 'issue_comments': issue_comments, 'repoIssuesCommentForm': repoIssuesCommentForm, 'page': page, 'total_page': range(0,total_page+1)}
    response_dictionary.update(ISSUES_ATTRS)
    return render_to_response('repo/issues_show.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

def issues_create(request, user_name, repo_name, issues_id):
    refs = 'master'; path = '.'; current = 'issues'
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    repoIssuesForm = RepoIssuesForm()
    issues = Issues()
    if issues_id != 0:
        issues = RepoManager.get_issues(repo.id, issues_id)
        if issues is None:
            issues = Issues()
        repoIssuesForm = RepoIssuesForm(instance = issues)
    repoIssuesForm.fill_assigned(repo)
    error = ''
    if request.method == 'POST':
        issues.user_id = request.user.id
        issues.repo_id = repo.id
        repoIssuesForm = RepoIssuesForm(request.POST, instance = issues)
        repoIssuesForm.fill_assigned(repo)
        if repoIssuesForm.is_valid():
            nid = repoIssuesForm.save().id
            return HttpResponseRedirect('/%s/%s/issues/%s/' % (user_name, repo_name, nid))
        else:
            error = u'issues 内容不能为空'
    response_dictionary = {'current': current, 'user_name': user_name, 'repo_name': repo_name, 'refs': refs, 'path': path, 'repoIssuesForm': repoIssuesForm, 'error': error, 'issues_id': issues_id}
    response_dictionary.update(ISSUES_ATTRS)
    return render_to_response('repo/issues_create.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

#TODO
def issues_delete(request, user_name, repo_name, issue_id):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    issues = RepoManager.get_issues(repo.id, issue_id)
    if issues is not None:
        issues.visibly = 1
        issues.save()
    return HttpResponse(json.dumps({'result': 'ok'}), mimetype="application/json")

#TODO
def issues_comment_delete(request, user_name, repo_name, comment_id):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    issues_comment = RepoManager.get_issues_comment(comment_id)
    if issues_comment is not None:
        issues = RepoManager.get_issues(repo.id, issues_comment.issues_id)
        if issues is not None:
            issues_comment.visibly = 1
            issues_comment.save()
            issues.comment_count = issues.comment_count - 1
            issues.save()
    return HttpResponse(json.dumps({'result': 'ok'}), mimetype="application/json")

def repo_network(request, user_name, repo_name):
    refs = 'master'; path = '.'; current = 'network'
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    repoMemberForm = RepoMemberForm()
    if request.method == 'POST':
        repoMemberForm = RepoMemberForm(request.POST)
        if repoMemberForm.is_valid():
            username = repoMemberForm.cleaned_data['username'].strip()
            action = repoMemberForm.cleaned_data['action']
            if action == 'add_member':
                RepoManager.add_member(repo.id, username)
            if action == 'remove_member':
                RepoManager.remove_member(repo.id, username)
    user_id = request.user.id
    member_ids = [o.user_id for o in RepoManager.list_repomember(repo.id)]
    member_ids.insert(0, repo.user_id)
    if user_id != repo.user_id and user_id in member_ids:
        member_ids.remove(user_id)
        member_ids.insert(0, user_id)
    merge_user_map = UserprofileManager.map_users(member_ids)
    members_vo = [merge_user_map[o] for o in member_ids]
    response_dictionary = {'current': current, 'user_name': user_name, 'repo_name': repo_name, 'refs': refs, 'path': path, 'members_vo': members_vo, 'repoMemberForm': repoMemberForm}
    return render_to_response('repo/network.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

def repo_clone_watch(request, user_name, repo_name):
    refs = 'master'; path = '.'; current = 'branches'
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
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
    watch_users = RepoManager.list_watch_user(repo.id)
    response_dictionary = {'current': current, 'user_name': user_name, 'repo_name': repo_name, 'refs': refs, 'path': path, 'fork_repos_tree': fork_repos_tree, 'watch_users': watch_users, 'test': {1, 1}}
    return render_to_response('repo/clone_watch.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

def repo_stats(request, user_name, repo_name):
    refs = 'master'; path = '.'; current = 'stats'
    response_dictionary = {'current': 'stats', 'user_name': user_name, 'repo_name': repo_name, 'refs': refs, 'path': path}
    return render_to_response('repo/clone_watch.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

def change_to_vo(raw_fork_repos_tree):
    user_ids = []
    for raw_fork_repos in raw_fork_repos_tree:
        for raw_fork_repo in raw_fork_repos:
            user_ids.append(raw_fork_repo.user_id)
    fork_repos_tree = []
    user_map = UserprofileManager.map_users(user_ids)
    for raw_fork_repos in raw_fork_repos_tree:
        fork_repos_tree.append(conver_repos(raw_fork_repos, user_map))
    return fork_repos_tree

def repo_refs(request, user_name, repo_name):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        return HttpResponse(json.dumps({'user_name': user_name, 'repo_name': repo_name, 'branches': [], 'tags': []}), mimetype="application/json")
    repopath = repo.get_abs_repopath(user_name)

    gitHandler = GitHandler()
    branches_refs = gitHandler.repo_ls_branches(repopath)
    tags_refs = gitHandler.repo_ls_tags(repopath)
    response_dictionary = {'user_name': user_name, 'repo_name': repo_name, 'branches': branches_refs, 'tags': tags_refs}
    return HttpResponse(json.dumps(response_dictionary), mimetype="application/json")

# TODO
@login_required
def edit(request, rid):
    error = u''
    repo = Repo()
    if rid != '0':
        try:
            repo = Repo.objects.get(id = rid, user_id = request.user.id)
        except Repo.DoesNotExist:
            pass
    repoForm = RepoForm(instance = repo)
    repo.user_id = request.user.id
    if request.method == 'POST':
        repoForm = RepoForm(request.POST, instance = repo)
        if repoForm.is_valid() and re.match("^\w+$", repoForm.cleaned_data['name']):
            fulfill_gitrepo(request.user.username, repoForm.cleaned_data['name'], repoForm.cleaned_data['auth_type'])
            repoForm.save()
            return HttpResponseRedirect('/' + request.user.username + '/repo/')
        else:
            error = u'输入正确的仓库名称[A-Za-z0-9_]，选择好语言和可见度'
    response_dictionary = {'repoForm': repoForm, 'rid': rid, 'error': error}
    return render_to_response('repo/edit.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

def get_commits_by_ids(ids):
    return RepoManager.get_commits_by_ids(ids)

def fulfill_gitrepo(username, reponame, auth_type):
    for base_repo_path in [PUBLIC_REPO_PATH, PRIVATE_REPO_PATH]:
        user_repo_path = '%s/%s' % (base_repo_path, username)
        if not os.path.exists(user_repo_path):
            os.makedirs(user_repo_path)
    pub_repo_path = ('%s/%s/%s.git' % (PUBLIC_REPO_PATH, username, reponame))
    pri_repo_path = ('%s/%s/%s.git' % (PRIVATE_REPO_PATH, username, reponame))
    if auth_type == '0': 
        if not os.path.exists(pub_repo_path):
            if os.path.exists(pri_repo_path):
                shutil.move(pri_repo_path, pub_repo_path)
            else:
                shutil.copytree(GIT_BARE_REPO_PATH, pub_repo_path)             
    else:
        if not os.path.exists(pri_repo_path):
            if os.path.exists(pub_repo_path):
                shutil.move(pub_repo_path, pri_repo_path)
            else:
                shutil.copytree(GIT_BARE_REPO_PATH, pri_repo_path)             


