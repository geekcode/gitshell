#!/python
# -*- coding: utf-8 -*-
import os, re
import time, json, hashlib, shutil
from django.core.cache import cache
from subprocess import check_output
from chardet.universaldetector import UniversalDetector
from gitshell.objectscache.models import CacheKey
from gitshell.viewtools.views import json_httpResponse
from gitshell.settings import PULLREQUEST_REPO_PATH
"""
git ls-tree `cat .git/refs/heads/master` -- githooks/
git log -1 --pretty='%ct %s' -- githooks/
git show HEAD:README.md
git diff 2497dbb67cb29c0448a3c658ed50255cb4de6419 a2f5ec702e58eb5053fc199c590eac29a2627ad7 --
path: . means is root of the repo path
"""
BINARY_FILE_TYPE = set(['doc', 'docx', 'msg', 'odt', 'pages', 'rtf', 'wpd', 'wps', 'azw', 'dat', 'efx', 'epub', 'gbr', 'ged', 'ibooks', 'key', 'keychain', 'pps', 'ppt', 'pptx', 'sdf', 'tar', 'vcf', 'aif', 'iff', 'm3u', 'm4a', 'mid', 'mp3', 'mpa', 'ra', 'wav', 'wma', '3g2', '3gp', 'asf', 'asx', 'avi', 'flv', 'mov', 'mp4', 'mpg', 'rm', 'srt', 'swf', 'vob', 'wmv', '3dm', '3ds', 'max', 'obj', 'bmp', 'dds', 'dng', 'gif', 'jpeg', 'jpg', 'png', 'webp', 'tiff', 'psd', 'pspimage', 'tga', 'thm', 'tif', 'yuv', 'ai', 'eps', 'ps', 'indd', 'pct', 'pdf', 'xlr', 'xls', 'xlsx', 'accdb', 'db', 'dbf', 'mdb', 'pdb', 'apk', 'app', 'com', 'exe', 'gadget', 'jar', 'pif', 'wsf', 'dem', 'gam', 'nes', 'rom', 'sav', 'dwg', 'dxf', 'gpx', 'cfm', 'crx', 'plugin', 'fnt', 'fon', 'otf', 'ttf', 'cab', 'cpl', 'cur', 'dll', 'dmp', 'drv', 'icns', 'ico', 'lnk', 'sys', 'prf', 'hqx', 'mim', 'uue', '7z', 'cbr', 'deb', 'gz', 'pkg', 'rar', 'rpm', 'sit', 'sitx', 'tar.gz', 'zip', 'zipx', 'bin', 'cue', 'dmg', 'iso', 'mdf', 'toast', 'vcd', 'class', 'fla', 'tmp', 'crdownload', 'ics', 'msi', 'part', 'torrent'])
class GitHandler():

    def __init__(self):
        self.empty_commit_hash = '0000000000000000000000000000000000000000'
        self.stage_path = '/opt/repo/stage'
        self.blank_p = re.compile(r'\s+')

    def repo_ls_tree(self, repo_path, commit_hash, path):
        if not self.path_check_chdir(repo_path, commit_hash, path):
            return None
        stage_file = self.get_stage_file(repo_path, commit_hash, path)
        result = self.read_load_stage_file(stage_file)
        if result is not None:
            return result
        result = self.ls_tree_check_output(commit_hash, path)
        self.dumps_write_stage_file(result, stage_file)
        return result
    
    def repo_cat_file(self, repo_path, commit_hash, path):
        if not self.path_check_chdir(repo_path, commit_hash, path):
            return None
        file_type = path.split('.')[-1]
        if file_type in BINARY_FILE_TYPE:
            return "二进制文件"
        stage_file = self.get_stage_file(repo_path, commit_hash, path)
        result = self.read_load_stage_file(stage_file)
        if result is not None:
            return result
        command = '/usr/bin/git show %s:%s | /usr/bin/head -c 524288' % (commit_hash, path)
        try:
            result = check_output(command, shell=True)
            ud = UniversalDetector()
            ud.feed(result)
            ud.close()
            if ud.result['encoding']:
                encoding = ud.result['encoding']
                if encoding != 'utf-8' or encoding != 'utf8':
                    result = result.decode(encoding).encode('utf-8')
            self.dumps_write_stage_file(result, stage_file)
            return result
        except Exception, e:
            print e
            return None
    
    def repo_log_file(self, repo_path, from_commit_hash, commit_hash, path):
        if not self.path_check_chdir(repo_path, commit_hash, path) or not re.match('^\w+$', from_commit_hash):
            return None
        between_commit_hash = from_commit_hash + '...' + commit_hash
        stage_file = self.get_stage_file(repo_path, between_commit_hash, path)
        stage_file = stage_file + '.log'
        result = self.read_load_stage_file(stage_file)
        if result is not None:
            return result
        result = self.repo_load_log_file(from_commit_hash, commit_hash, path)
        self.dumps_write_stage_file(result, stage_file)
        return result

    def repo_load_log_file(self, from_commit_hash, commit_hash, path):
        commits = []
        between_commit_hash = from_commit_hash
        if commit_hash is not None and not commit_hash.startswith('0000000'):
            between_commit_hash = from_commit_hash + '...' + commit_hash
        command = '/usr/bin/git log -50 --pretty="%%h______%%t______%%an______%%cn______%%ct|%%s" %s -- %s | /usr/bin/head -c 524288' % (between_commit_hash, path)
        try:
            raw_result = check_output(command, shell=True)
            for line in raw_result.split('\n'):
                ars = line.split('|', 1)
                if len(ars) != 2:
                    continue
                attr, commit_message = ars
                attrs = attr.split('______', 5)
                if len(attrs) != 5:
                    continue
                (commit_hash, tree_hash, author, committer, committer_date) = (attrs)
                commits.append({
                    'commit_hash': commit_hash,
                    'tree_hash': tree_hash,
                    'author': author,
                    'committer': committer,
                    'committer_date': committer_date,
                    'commit_message': commit_message,
                })
            return commits
        except Exception, e:
            print e
            return None
    
    def repo_diff(self, repo_path, pre_commit_hash, commit_hash, path):
        if not self.path_check_chdir(repo_path, commit_hash, path) or not re.match('^\w+$', pre_commit_hash):
            return None
        stage_file = self.get_diff_stage_file(repo_path, pre_commit_hash, commit_hash, path)
        stage_file = stage_file + '.diff'
        result = self.read_load_stage_file(stage_file)
        if result is not None:
            return result
        command = '/usr/bin/git diff %s..%s -- %s | /usr/bin/head -c 524288' % (pre_commit_hash, commit_hash, path)
        try:
            result = check_output(command, shell=True)
            self.dumps_write_stage_file(result, stage_file)
            return result
        except Exception, e:
            print e
            return None

    def get_diff_stage_file(self, repo_path, pre_commit_hash, commit_hash, path):
        (username, reponame) = repo_path.split('/')[-2:]
        stage_file = '%s/%s/%s/%s' % (self.stage_path, username, reponame, hashlib.md5('%s|%s|%s' % (pre_commit_hash, commit_hash, path)).hexdigest())
        return stage_file

    def get_stage_file(self, repo_path, commit_hash, path):
        (username, reponame) = repo_path.split('/')[-2:]
        stage_file = '%s/%s/%s/%s' % (self.stage_path, username, reponame, hashlib.md5('%s|%s' % (commit_hash, path)).hexdigest())
        return stage_file
        
    # TODO load or not ?
    def read_load_stage_file(self, stage_file):
        if os.path.exists(stage_file):
            try:
                json_data = open(stage_file)
                result = json.load(json_data)
                return result
            except Exception, e:
                print e
                return None
            finally:
                json_data.close()

    def ls_tree_check_output(self, commit_hash, path):
        command = '/usr/bin/git ls-tree %s -- %s | /usr/bin/head -c 524288' % (commit_hash, path)
        result = {}
        try:
            raw_result = check_output(command, shell=True)
            max = 100
            for line in raw_result.split("\n"):
                array = self.blank_p.split(line) 
                if len(array) >= 4:
                    relative_path = array[3]
                    if path != '.':
                        relative_path = relative_path[len(path):]
                    if array[1] == 'tree':
                        relative_path = relative_path + '/'
                    if self.is_allowed_path(relative_path):
                        result[relative_path] = array[1:3]
                if(max <= 0):
                    break
                max = max - 1
            if len(path.split('/')) < 30:
                pre_path = path
                if path == '.':
                    pre_path = ''
                last_commit_command = 'for i in %s; do echo -n "$i "; git log %s -1 --pretty="%%ct %%an %%s" -- %s$i | /usr/bin/head -c 524288; done' % (' '.join(result.keys()), commit_hash, pre_path)
                last_commit_output = check_output(last_commit_command, shell=True)
                for last_commit in last_commit_output.split('\n'):
                    last_commit_array = last_commit.split(' ', 3)
                    if len(last_commit_array) > 3:
                        (relative_path, unixtime, author_name, last_commit_message) = last_commit_array
                        result[relative_path].append(unixtime)
                        result[relative_path].append(author_name)
                        result[relative_path].append(last_commit_message)
            return result
        except Exception, e:
            print e
            return None

    def dumps_write_stage_file(self, result, stage_file):
        if result is None:
            return
        timenow = int(time.time()) 
        stage_file_tmp = '%s.%s' % (stage_file, timenow)
        stage_file_tmp_path = os.path.dirname(stage_file_tmp)
        if not os.path.exists(stage_file_tmp_path):
            os.makedirs(stage_file_tmp_path)
        try:
            stage_file_w = open(stage_file_tmp, 'w')
            stage_file_w.write(json.dumps(result))
            stage_file_w.flush()
            shutil.move(stage_file_tmp, stage_file)
        except Exception, e:
            print e
        finally:
            if os.path.exists(stage_file_tmp):
                os.remove(stage_file_tmp)
            stage_file_w.close()

    def path_check_chdir(self, repo_path, commit_hash, path):
        if not self.is_allowed_path(repo_path) or not self.is_allowed_path(path) or not re.match('^\w+$', commit_hash) or not os.path.exists(repo_path):
            return False
        if len(path.split('/')) > 50 or self.chdir(repo_path) is False:
            return False
        if len(repo_path) > 256 or len(commit_hash) > 256 or len(path) > 256:
            return False
        return True
    
    def repo_ls_tags_branches(self, repo, repo_path):
        tags = self.repo_ls_tags(repo, repo_path)
        branches = self.repo_ls_branches(repo, repo_path)
        return {'tags': tags, 'branches': branches}

    def repo_ls_tags(self, repo, repo_path):
        cacheKey = CacheKey.REFS_TAG % repo.id
        tags = cache.get(cacheKey)
        if tags is not None:
            return tags
        tags = []
        dirpath = '%s/refs/tags' % repo_path
        if not self.is_allowed_path(dirpath) or not os.path.exists(dirpath):
            return tags
        max = 20
        for tag in os.listdir(dirpath):
            if self.is_allowed_path(tag):
                tags.append(tag)
                max = max - 1
                if(max <= 0):
                    break
        tags.sort()
        tags.reverse()
        cache.add(cacheKey, tags, 3600)
        return tags
    
    def repo_ls_branches(self, repo, repo_path):
        cacheKey = CacheKey.REFS_BRANCH % repo.id
        branches = cache.get(cacheKey)
        if branches is not None:
            return branches
        branches = []
        dirpath = '%s/refs/heads' % repo_path
        if not self.is_allowed_path(dirpath) or not os.path.exists(dirpath):
            return branches
        max = 20
        for branch in os.listdir(dirpath):
            if self.is_allowed_path(branch):
                if branch == 'master':
                    branches.insert(0, branch)
                else:
                    branches.append(branch)
                max = max - 1
                if(max <= 0):
                    break
        cache.add(cacheKey, branches, 3600)
        return branches
    
    """ refs: branch, tag """
    def get_commit_hash(self, repo, repo_path, refs):
        commit_hash = self._get_commit_hash_by_cache(repo, refs)
        if commit_hash is not None:
            return commit_hash
        refs_path = '%s/refs/heads/%s' % (repo_path, refs)
        if not os.path.exists(refs_path):
            refs_path = '%s/refs/tags/%s' % (repo_path, refs)
        if not self.is_allowed_path(refs_path):
            return self.empty_commit_hash
        if os.path.exists(refs_path):
            f = None
            try:
                f = open(refs_path, 'r')
                commit_hash = f.read(40)
                if re.match('^\w+$', commit_hash):
                    self._cache_commit_hash(repo, refs, commit_hash)
                    return commit_hash
            finally:
                if f != None:
                    f.close()
        packed_refs_path = '%s/packed-refs' % (repo_path)
        blank_p = re.compile(r'\s+')
        full_heads_refs = 'refs/heads/%s' % refs
        full_tags_refs = 'refs/tags/%s' % refs
        if os.path.exists(packed_refs_path):
            refs_f = None
            try:
                refs_f = open(packed_refs_path, 'r')
                for line in refs_f:
                    if line.startswith('#'):
                        continue
                    array = blank_p.split(line)
                    if len(array) >= 2:
                        commit_hash = array[0].strip()
                        refs_from_f = array[1].strip()
                        if refs_from_f == full_heads_refs or refs_from_f == full_tags_refs:
                            self._cache_commit_hash(repo, refs, commit_hash)
                            return commit_hash
            finally:
                if refs_f != None:
                    refs_f.close()
        return self.empty_commit_hash

    def prepare_pull_request(self, pullRequest, source_repo, desc_repo):
        pullrequest_repo_path = '%s/%s/%s' % (PULLREQUEST_REPO_PATH, desc_repo.get_repo_username(), desc_repo.name)
        source_abs_repopath = source_repo.get_abs_repopath(source_repo.get_repo_username())
        source_remote_name = '%s-%s' % (source_repo.get_repo_username(), source_repo.name)
        dest_abs_repopath = desc_repo.get_abs_repopath(desc_repo.get_repo_username())
        desc_remote_name = '%s-%s' % (desc_repo.get_repo_username(), desc_repo.name)
        action = 'prepare'
        args = [pullrequest_repo_path, source_abs_repopath, source_remote_name, dest_abs_repopath, desc_remote_name, action]
        if not self.is_allowed_paths(args):
            return False
        command = '/bin/bash /opt/bin/git-pullrequest.sh %s %s %s %s %s %s' % tuple(args)
        try:
            check_output(command, shell=True)
            return True
        except Exception, e:
            print e
            return False

    def merge_pull_request(self, pullRequest, source_repo, desc_repo):
        pass

    def _get_commit_hash_by_cache(self, repo, refs):
        cacheKey = CacheKey.REFS_REPO_COMMIT_VERSION % repo.id
        version = cache.get(cacheKey)
        if version is not None:
            cacheKey = CacheKey.REFS_COMMIT_HASH % (str(repo.id), version, refs)
            commit_hash = cache.get(cacheKey)
            if commit_hash is not None:
                return commit_hash
        return None

    def _cache_commit_hash(self, repo, refs, commit_hash):
        cacheKey = CacheKey.REFS_REPO_COMMIT_VERSION % repo.id
        version = cache.get(cacheKey)
        if version is None:
            version = time.time()
            cache.add(cacheKey, version, 3600)
        cacheKey = CacheKey.REFS_COMMIT_HASH % (str(repo.id), version, refs)
        cache.add(cacheKey, commit_hash, 3600)
    
    def is_allowed_paths(self, paths):
        for path in paths:
            if not self.is_allowed_path(path):
                return False
        return True

    def is_allowed_path(self, path):
        if '..' in path:
            return False
        if re.match('^[a-zA-Z0-9_\.\-/]+$', path):
            return True
        return False

    def chdir(self, path):
        try:
            os.chdir(path)
            return True
        except Exception, e:
            print e
            return False

if __name__ == '__main__':
    gitHandler = GitHandler()
    #print gitHandler.repo_ls_branches('/opt/8001/gitshell/.git')
    #print gitHandler.get_commit_hash('/opt/8001/gitshell/.git', 'refs/heads/master')
    print gitHandler.is_allowed_path('abc')
    print gitHandler.is_allowed_path('abc b')
    print gitHandler.is_allowed_path('abc-_/.b')
    print gitHandler.repo_ls_tree('/opt/8001/gitshell/.git', '16d71ee5f6131254c7865951bf277ffe4bde1cf9', 'githooks/')
    print gitHandler.repo_ls_tree('/opt/8001/gitshell/.git', '16d71ee5f6131254c7865951bf277ffe4bde1cf9', '.')
    print gitHandler.repo_cat_file('/opt/8001/gitshell/.git', '16d71ee5f6131254c7865951bf277ffe4bde1cf9', 'README.md')
    print gitHandler.repo_log_file('/opt/8001/gitshell/.git', '16d71ee5f6131254c7865951bf277ffe4bde1cf9', '0000000', 'README.md')
    print gitHandler.repo_diff('/opt/8001/gitshell/.git', '7daf915', '1e25868', 'README.md')
