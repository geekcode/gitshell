#!/usr/bin/python

import os, re
from subprocess import Popen
from subprocess import PIPE
"""
git ls-tree `cat .git/refs/heads/master` -- githooks/
git log -1 --pretty='%ct  %s' -- githooks/
git show HEAD:README.md
git diff 2497dbb67cb29c0448a3c658ed50255cb4de6419 a2f5ec702e58eb5053fc199c590eac29a2627ad7 --
"""
class GitHandler():
    # TODO path too loong limit, file and tree limit
    def repo_ls_tree(self, repo_path, commit_hash, path):
        if not self.path_check(repo_path, commit_hash, path):
            return None
        args = ['/usr/bin/git', 'ls-tree', commit_hash, '--', path]
        popen = Popen(args, stdout=PIPE, shell=False, close_fds=True)
        result = popen.communicate()[0]
        return result
    
    def repo_cat_file(self, repo_path, commit_hash, path):
        if not self.path_check(repo_path, commit_hash, path):
            return None
        args = ['/usr/bin/git', 'show', '%s:%s' % (commit_hash, path)]
        popen = Popen(args, stdout=PIPE, shell=False, close_fds=True)
        result = popen.communicate()[0]
        return result
    
    def repo_log_file(self, repo_path, commit_hash, path):
        if not self.path_check(repo_path, commit_hash, path):
            return None
        args = ['/usr/bin/git', 'log', '-10', '--pretty=%h  %p  %t  %an  %cn  %ct  %s', commit_hash, '--', path]
        popen = Popen(args, stdout=PIPE, shell=False, close_fds=True)
        result = popen.communicate()[0]
        return result
    
    def repo_diff(self, repo_path, pre_commit_hash, commit_hash, path):
        if not self.path_check(repo_path, commit_hash, path) or not re.match('^\w+$', pre_commit_hash):
            return None
        args = ['/usr/bin/git', 'diff', '%s..%s' % (pre_commit_hash, commit_hash), '--', path]
        popen = Popen(args, stdout=PIPE, shell=False, close_fds=True)
        result = popen.communicate()[0]
        return result

    def path_check(self, repo_path, commit_hash, path):
        if not self.is_allowed_path(repo_path) or not self.is_allowed_path(path) or not re.match('^\w+$', commit_hash) or not os.path.exists(repo_path):
            return False
        if len(path.split('/')) > 50 or self.chdir(repo_path) is False:
            return False
        return True
    
    def repo_ls_tags(self, repo_path):
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
        return tags
    
    def repo_ls_branches(self, repo_path):
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
        return branches
    
    empty_commit_hash = '0000000000000000000000000000000000000000'
    """ refs: branch, tag """
    def get_commit_hash(self, repo_path, refs):
        refs_path = '%s/%s' % (repo_path, refs)
        if '..' in refs_path or not self.is_allowed_path(refs_path):
            return self.empty_commit_hash
        if os.path.exists(refs_path):
            f = None
            try:
                f = open(refs_path, 'r')
                commit_hash = f.read(40)
                if re.match('^\w+$', commit_hash):
                    return commit_hash
            finally:
                if f != None:
                    f.close()
        return self.empty_commit_hash
    
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
            return False

if __name__ == '__main__':
    gitHandler = GitHandler()
    print gitHandler.repo_ls_branches('/opt/8001/gitshell/.git')
    print gitHandler.get_commit_hash('/opt/8001/gitshell/.git', 'refs/heads/master')
    print gitHandler.is_allowed_path('abc')
    print gitHandler.is_allowed_path('abc b')
    print gitHandler.is_allowed_path('abc-_:/.b')
    print gitHandler.repo_ls_tree('/opt/8001/gitshell/.git', '16d71ee5f6131254c7865951bf277ffe4bde1cf9', 'githooks/')
    print gitHandler.repo_ls_tree('/opt/8001/gitshell/.git', '16d71ee5f6131254c7865951bf277ffe4bde1cf9', '.')
    print gitHandler.repo_cat_file('/opt/8001/gitshell/.git', '16d71ee5f6131254c7865951bf277ffe4bde1cf9', 'README.md')
    print gitHandler.repo_log_file('/opt/8001/gitshell/.git', '16d71ee5f6131254c7865951bf277ffe4bde1cf9', 'README.md')
    print gitHandler.repo_diff('/opt/8001/gitshell/.git', '7daf915', '1e25868', 'README.md')