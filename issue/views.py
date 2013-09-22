# -*- coding: utf-8 -*-  
import os, re
import json, time, urllib
import shutil, copy, random
from datetime import datetime, timedelta
from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.template import RequestContext
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.contrib.auth.models import User
from django.shortcuts import render_to_response
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError
from django.utils.html import escape
from gitshell.repo.models import RepoManager
from gitshell.repo.views import get_common_repo_dict
from gitshell.gsuser.models import GsuserManager
from gitshell.issue.models import IssueManager, Issue, IssueComment, ISSUE_STATUS
from gitshell.issue.Forms import IssueForm, IssueCommentForm
from gitshell.issue.cons import TRACKERS, STATUSES, PRIORITIES, TRACKERS_VAL, STATUSES_VAL, PRIORITIES_VAL, ISSUE_ATTRS, conver_issues, conver_issue_comments
from gitshell.gsuser.decorators import repo_permission_check, repo_source_permission_check
from gitshell.feed.models import FeedManager
from gitshell.viewtools.views import json_httpResponse

@repo_permission_check
def issues(request, user_name, repo_name):
    return issues_list(request, user_name, repo_name, '0', '0', '0', '0', 'modify_time', 0)
 
@repo_permission_check
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
    members = GsuserManager.list_user_by_ids(member_ids)
    assigneds = [o.username for o in members]
    assigneds.insert(0, '0')
    if assigned is None:
        assigned = assigneds[0]
    assigned_id = 0
    assigned_user = GsuserManager.get_user_by_name(assigned)
    if assigned_user is not None and assigned in assigneds:
        assigned_id = assigned_user.id
    tracker = int(tracker); status = int(status); priority = int(priority); page = int(page)
    current_attrs = { 'assigned': str(assigned), 'tracker': tracker, 'status': status, 'priority': priority, 'orderby': str(orderby), 'page': page }
    raw_issues = []
    page_size = 50
    offset = page*page_size
    row_count = page_size + 1
    if assigned_id == 0 and tracker == 0 and status == 0 and priority == 0:
        raw_issues = IssueManager.list_issues(repo.id, orderby, offset, row_count)
    else:
        assigned_ids = member_ids if assigned_id == 0 else [assigned_id]
        trackeres = TRACKERS_VAL if tracker == 0 else [tracker]
        statuses = STATUSES_VAL if status == 0 else [status]
        priorities = PRIORITIES_VAL if priority == 0 else [priority] 
        raw_issues = IssueManager.list_issues_cons(repo.id, assigned_ids, trackeres, statuses, priorities, orderby, offset, row_count)
    reporter_ids = [o.user_id for o in raw_issues]
    reporters = GsuserManager.list_user_by_ids(list(set(reporter_ids)-set(member_ids)))
    username_map = {}
    for member in members:
        username_map[member.id] = member.username
    for reporter in reporters:
        username_map[reporter.id] = reporter.username
    issues = conver_issues(raw_issues, username_map, {repo.id: repo.name})

    hasPre = False ; hasNext = False
    if page > 0:
        hasPre = True 
    if len(issues) > page_size:
        hasNext = True
        issues.pop()
    
    response_dictionary = {'mainnav': 'repo', 'current': current, 'path': path, 'assigneds': assigneds, 'assigned': assigned, 'tracker': tracker, 'status': status, 'priority': priority, 'orderby': orderby, 'page': page, 'current_attrs': current_attrs, 'issues': issues, 'hasPre': hasPre, 'hasNext': hasNext}
    response_dictionary.update(ISSUE_ATTRS)
    response_dictionary.update(get_common_repo_dict(request, repo, user_name, repo_name, refs))
    return render_to_response('repo/issues.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

@repo_permission_check
def show_default(request, user_name, repo_name, issue_id):
    return show(request, user_name, repo_name, issue_id, None)

@repo_permission_check
def show(request, user_name, repo_name, issue_id, page):
    refs = 'master'; path = '.'; current = 'issues'
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    raw_issue = IssueManager.get_issue(repo.id, issue_id)
    if raw_issue is None:
        raise Http404
    issueCommentForm = IssueCommentForm()
    if request.method == 'POST' and request.user.is_authenticated():
        issueComment = IssueComment() 
        issueComment.issue_id = issue_id
        issueComment.user_id = request.user.id
        issueCommentForm = IssueCommentForm(request.POST, instance = issueComment)
        if issueCommentForm.is_valid():
            cid = issueCommentForm.save().id
            FeedManager.notif_issue_comment_at(request.user.id, cid, issueCommentForm.cleaned_data['content'])
            raw_issue.comment_count = raw_issue.comment_count + 1
            raw_issue.save()
            return HttpResponseRedirect('/%s/%s/issues/%s/' % (user_name, repo_name, issue_id))
    username_map = {}
    users = GsuserManager.list_user_by_ids([raw_issue.user_id, raw_issue.assigned])
    for user in users:
        username_map[user.id] = user.username
    issue = conver_issues([raw_issue], username_map, {repo.id: repo.name})[0]
    
    page_size = 50
    total_count = issue['comment_count']
    total_page = total_count / page_size
    if total_count != 0 and total_count % page_size == 0:
        total_page = total_page - 1
    if page is None or int(page) > total_page:
        page = total_page
    page = int(page)
    user_img_map = {}
    issue_comments = []
    if total_count > 0:
        offset = page*page_size
        row_count = page_size
        raw_issue_comments = IssueManager.list_issue_comments(issue_id, offset, row_count)
        user_ids = [o.user_id for o in raw_issue_comments]
        users = GsuserManager.list_user_by_ids(user_ids)
        userprofiles = GsuserManager.list_userprofile_by_ids(user_ids)
        for user in users:
            username_map[user.id] = user.username
        for userprofile in userprofiles:
            user_img_map[userprofile.id] = userprofile.imgurl 
        issue_comments = conver_issue_comments(raw_issue_comments, username_map, user_img_map)

    member_ids = [o.user_id for o in RepoManager.list_repomember(repo.id)]
    member_ids.insert(0, repo.user_id)
    if raw_issue.user_id != repo.user_id and request.user.id in member_ids:
        member_ids.remove(request.user.id)
        member_ids.insert(0, request.user.id)
    members = GsuserManager.list_user_by_ids(member_ids)
    assigneds = [o.username for o in members]

    has_issue_modify_right = _has_issue_modify_right(request, raw_issue, repo)
    response_dictionary = {'mainnav': 'repo', 'current': current, 'path': path, 'issue': issue, 'issue_comments': issue_comments, 'issueCommentForm': issueCommentForm, 'page': page, 'total_page': range(0, total_page+1), 'assigneds': assigneds, 'assigned': issue['assigned'], 'tracker': raw_issue.tracker, 'status': raw_issue.status, 'priority': raw_issue.priority, 'has_issue_modify_right': has_issue_modify_right}
    response_dictionary.update(ISSUE_ATTRS)
    response_dictionary.update(get_common_repo_dict(request, repo, user_name, repo_name, refs))
    return render_to_response('repo/issue_show.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

@login_required
@repo_permission_check
def create(request, user_name, repo_name):
    refs = 'master'; path = '.'; current = 'issues'
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    issue = Issue()
    issue.priority = 3
    issueForm = IssueForm(instance = issue)
    issueForm.fill_assigned(repo)
    error = u''
    if request.method == 'POST':
        issue.user_id = repo.user_id
        issue.repo_id = repo.id
        issue.creator_user_id = request.user.id
        issueForm = IssueForm(request.POST, instance = issue)
        issueForm.fill_assigned(repo)
        if issueForm.is_valid():
            newIssue = issueForm.save()
            nid = newIssue.id
            FeedManager.notif_issue_at(request.user.id, nid, issueForm.cleaned_data['subject'] + ' ' + issueForm.cleaned_data['content'])
            FeedManager.notif_issue_status(request.user, newIssue, ISSUE_STATUS.ASSIGNED)
            FeedManager.feed_issue_change(request.user, repo, None, nid)
            return HttpResponseRedirect('/%s/%s/issues/%s/' % (user_name, repo_name, nid))
        else:
            error = u'issue 内容不能为空'
    response_dictionary = {'mainnav': 'repo', 'current': current, 'path': path, 'issueForm': issueForm, 'error': error}
    response_dictionary.update(ISSUE_ATTRS)
    response_dictionary.update(get_common_repo_dict(request, repo, user_name, repo_name, refs))
    return render_to_response('repo/issue_create.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

@login_required
@repo_permission_check
def edit(request, user_name, repo_name, issue_id):
    refs = 'master'; path = '.'; current = 'issues'
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    issue = IssueManager.get_issue(repo.id, issue_id)
    has_issue_modify = _has_issue_modify_right(request, issue, repo)
    if issue is None or not has_issue_modify:
        raise Http404
    orgi_issue = copy.copy(issue)
    issueForm = IssueForm(instance = issue)
    issueForm.fill_assigned(repo)
    error = u''
    if request.method == 'POST':
        issueForm = IssueForm(request.POST, instance = issue)
        issueForm.fill_assigned(repo)
        if issueForm.is_valid():
            newIssue = issueForm.save()
            nid = newIssue.id
            FeedManager.notif_issue_at(request.user.id, nid, issueForm.cleaned_data['subject'] + ' ' + issueForm.cleaned_data['content'])
            FeedManager.notif_issue_status(request.user, newIssue, ISSUE_STATUS.ASSIGNED)
            FeedManager.feed_issue_change(request.user, repo, orgi_issue, nid)
            return HttpResponseRedirect('/%s/%s/issues/%s/' % (user_name, repo_name, nid))
        else:
            error = u'issue 内容不能为空'
    response_dictionary = {'mainnav': 'repo', 'current': current, 'path': path, 'issueForm': issueForm, 'error': error, 'issue_id': issue_id}
    response_dictionary.update(ISSUE_ATTRS)
    response_dictionary.update(get_common_repo_dict(request, repo, user_name, repo_name, refs))
    return render_to_response('repo/issue_edit.html',
                          response_dictionary,
                          context_instance=RequestContext(request))

@login_required
@repo_permission_check
@require_http_methods(["POST"])
def delete(request, user_name, repo_name, issue_id):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    issue = IssueManager.get_issue(repo.id, issue_id)
    if issue is not None:
        if _has_issue_modify_right(request, issue, repo):
            issue.visibly = 1
            issue.save()
    return _json_ok()

@login_required
@repo_permission_check
@require_http_methods(["POST"])
def update(request, user_name, repo_name, issue_id, attr):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        raise Http404
    issue = IssueManager.get_issue(repo.id, issue_id)
    if issue is None:
        return _json_failed()
    has_issue_modify_right = _has_issue_modify_right(request, issue, repo)
    if not has_issue_modify_right:
        return _json_failed()
    orgi_issue = copy.copy(issue)
    (key, value) = attr.split('___', 1)
    if key == 'assigned':
        user = GsuserManager.get_user_by_name(value)
        if user is None:
            return _json_failed()
        repoMember = RepoManager.get_repo_member(repo.id, user.id)
        if repoMember is None:
            return _json_failed()
        issue.assigned = repoMember.user_id
        issue.save()
        FeedManager.notif_issue_status(request.user, issue, ISSUE_STATUS.ASSIGNED)
        FeedManager.feed_issue_change(request.user, repo, orgi_issue, issue.id)
        return _json_ok()
    value = int(value)
    if key == 'tracker':
        issue.tracker = value
    elif key == 'status':
        issue.status = value
    elif key == 'priority':
        issue.priority = value
    issue.save()
    FeedManager.feed_issue_change(request.user, repo, orgi_issue, issue.id)
    return _json_ok()

@require_http_methods(["POST"])
@login_required
def do_issue(request):
    action = request.POST.get('action', '')
    comment = request.POST.get('comment', '')
    repo_id = request.POST.get('repo_id', '')
    issue_id = request.POST.get('issue_id', '')
    if action == '' or repo_id == '' or issue_id == '':
        return json_httpResponse({'result': 'failed'})
    repo = RepoManager.get_repo_by_id(int(repo_id))
    issue = IssueManager.get_issue(int(repo_id), int(issue_id))
    if repo is None or issue is None:
        return json_httpResponse({'result': 'failed'})
    if issue.assigned != request.user.id and repo.user_id != request.user.id:
        return json_httpResponse({'result': 'failed'})
    orgi_issue = copy.copy(issue)
    if action == 'fixed':
        issue.status = 4
    elif action == 'close':
        issue.status = 5
    elif action == 'reject':
        issue.status = 6
    if comment != '':
        issueComment = IssueComment() 
        issueComment.issue_id = issue.id
        issueComment.user_id = request.user.id
        issueComment.content = comment
        issueComment.save()
        issue.comment_count = issue.comment_count + 1
    issue.save()
    FeedManager.feed_issue_change(request.user, repo, orgi_issue, issue.id)
    response_dictionary = {'result': 'sucess'}
    return json_httpResponse(response_dictionary)
        
@login_required
@repo_permission_check
@require_http_methods(["POST"])
def comment_delete(request, user_name, repo_name, comment_id):
    repo = RepoManager.get_repo_by_name(user_name, repo_name)
    if repo is None:
        return _json_failed()
    issue_comment = IssueManager.get_issue_comment(comment_id)
    if issue_comment is None:
        return _json_failed()
    issue = IssueManager.get_issue(repo.id, issue_comment.issue_id)
    if issue is None or not _has_issue_comment_modify_right(request, issue_comment, repo):
        return _json_failed()
    issue_comment.visibly = 1
    issue_comment.save()
    issue.comment_count = issue.comment_count - 1
    issue.save()
    return _json_ok()

def _has_issue_modify_right(request, issue, repo):
    return issue is not None and (request.user.id == issue.user_id or request.user.id == repo.user_id)

def _has_issue_comment_modify_right(request, issue_comment, repo):
    return issue_comment is not None and (request.user.id == issue_comment.user_id or request.user.id == repo.user_id)

def _json_ok():
    return json_httpResponse({'result': 'ok'})

def _json_failed():
    return json_httpResponse({'result': 'failed'})


