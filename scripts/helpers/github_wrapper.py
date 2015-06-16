# -*- coding: utf-8 -*-
#
# GPL License and Copyright Notice ============================================
#  This file is part of Wrye Bash.
#
#  Wrye Bash is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  Wrye Bash is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Wrye Bash; if not, write to the Free Software Foundation,
#  Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#
#  Wrye Bash copyright (C) 2005-2009 Wrye, 2010-2014 Wrye Bash Team
#  https://github.com/wrye-bash
#
# =============================================================================

"""This module wraps github API calls. Features caching.
 Do not import from globals here !"""

import github
import os

USER_FILE = u'generate_second_posts.usr'
ALL_ISSUES = 'all'
DEFAULT_ISSUE_STATE = ALL_ISSUES
DEFAULT_MILESTONE = None

def getUser():
    """Attempts to load 'generate_second_posts.user' to read in user data for
       accessing GitHub API.  If the file is not present or the data invalid,
       prompts the user to input his or her data, and asks if it should be
       saved.
         Return: tuple either of:
             (username, password) - without 2 factor authentication
             (key,) - with 2 factor authentication
    """
    user = None
    password = None
    key = None
    if os.path.exists(USER_FILE):
        try:
            with open(USER_FILE) as ins:
                lines = ins.readlines()
            # filter out empty lines
            lines = [line.strip() for line in lines if line and line.strip()]
            if len(lines) == 1:
                # 2-factor authentication
                key = lines[0]
            elif len(lines) == 2:
                user, password = lines
        except:
            pass
    if (not user or not password) and (not key):
        # Invalid, prompt for input
        print ("User settings file missing or invalid data present.  Please "
               "input your information.  If you are using 2-factor"
               "authentication on your account, please see our Wiki page on "
               "setting up a Personal Access Token for this script.")
        print " 1) Entering a Personal Access Token"
        print " 2) Entering a user name and password"
        print " 3) Exit"
        input_ = raw_input(">")
        if input_ == '1':
            key = raw_input('token:').strip()
        elif input_ == '2':
            user = raw_input('user:').strip()
            password = raw_input('password:').strip()
        else:
            return ()
        print
        save = raw_input("Would you like to save these settings to the user "
                         "settings file? [Y/N]:")
        if save in ('y', 'Y'):
            with open(USER_FILE, 'w') as out:
                if key:
                    out.write(key)
                else:
                    out.write(user)
                    out.write('\n')
                    out.write(password)
    if key:
        return key,
    return user, password

def getRepo(git, orgName, repoName):
    """Get a githubapi repository object for the specified repository.
        git: github.Github object for the user
        orgName: display name of the orginizations for the repository
                 (not the link name, ie Wrye Bash is the name, but
                  wrye-bash is the link to access it).  If orgName is
                  None, assumes personal repos.
        repoName: name of the repository to get
    """
    # Try repos in organizations you're in
    if orgName:
        for org in git.get_user().get_orgs():
            if org.name == orgName:
                for repo in org.get_repos():
                    if repo.name == repoName:
                        print "Got repository from", orgName, "organization."
                        return repo
    # Try repos you own
    else:
        for repo in git.get_user().get_repos():
            if repo.name == repoName:
                print "Got repository from personal account."
                return repo
    # Try starred repos
    for repo in git.get_user().get_starred():
        if repo.name == repoName:
            print "Got repository from starred repositories."
            return repo
    # Try watched repos
    for repo in git.get_user().get_watched():
        if repo.name == repoName:
            print "Got repository from watched repositories."
            return repo
    return None

def getMilestone(repo, milestoneTitle):
    """Returns the github.Milestone object for a specified milestone."""
    for m in repo.get_milestones():
        if m.title == milestoneTitle:
            return m
    return None

class _IssueCache(object):
    CACHE = {}  # key: an IssueFilter --> value: a list of issues
    ALL_LABELS = {}  # key is an IssueFilter (but only Repo matters, TODO) and
    # value a list of issue labels for this repo - should be a set probably
    counter = 0

    class IssueFilter(object):
        def __init__(self, repo, milestone=None, state=None):
            self.repo = repo
            self.milestone = milestone
            self._state = state

        @property
        def state(self):
            if not self._state:  # disallow None - API's fault
                return DEFAULT_ISSUE_STATE
            return self._state

        def __key(self):  # http://stackoverflow.com/a/2909119/281545
            return self.repo, self.milestone, self.state

        def __eq__(self, other):  # add `self is other` optimization ?
            return type(other) is type(self) and self.__key() == other.__key()

        def __ne__(self, other):  # needed ?
            return not self.__eq__(other)

        def __hash__(self):
            return hash(self.__key())

        def __lt__(self, other):
            if self.repo != other.repo: return False
            if self.state != other.state and other.state != \
                    DEFAULT_ISSUE_STATE: return False
            if self.milestone != other.milestone and other.milestone:
                return False
            return True

    @staticmethod
    def hit(repo, milestone, state):
        issueFilter = _IssueCache.IssueFilter(repo, milestone, state)
        current = _IssueCache.CACHE.get(issueFilter)
        if not current:
            # search in the cache for some superset of issues already fetched
            super_ = None
            for key,issues in _IssueCache.CACHE.iteritems():
                if issueFilter < key:
                    super_ = issues
                    break
            if super_:
                if not milestone and not state: current = super_
                elif not milestone:
                    current = [x for x in super_ if x.state == state]
                elif not state:
                    current = [x for x in super_ if x.milestone == milestone]
                else:
                    current = [x for x in super_ if
                               x.state == state and x.milestone == milestone]
                _IssueCache._update(repo, milestone, state, current)
                return current
            # else fetch them...
            _IssueCache.counter += 1
            print "Hitting github for", _IssueCache.counter, "time"
            if milestone:  # FIXME - API won't let me specify None for all
                # milestone=github.GithubObject.NotSet ...
                current = repo.get_issues(milestone,
                                          state=issueFilter.state,
                                          sort='created',
                                          direction='desc')
            else:
                current = repo.get_issues(state=issueFilter.state,
                                          sort='created',
                                          direction='desc')
            _IssueCache._update(repo, milestone, state, current)
        return current

    @staticmethod
    def _update(repo, milestone, state, issues):  # not thread safe
        issueFilter = _IssueCache.IssueFilter(repo, milestone, state)
        _IssueCache.CACHE[issueFilter] = issues

    @staticmethod
    def allLabels(repo):
        issueFilter = _IssueCache.IssueFilter(repo)
        all_ = _IssueCache.ALL_LABELS.get(issueFilter)
        if not all_:
            all_ = _IssueCache.ALL_LABELS[issueFilter] = repo.get_labels()
        return set(all_)

def getIssues(repo, milestone=None, keep_labels=set(), skip_labels=set(),
              state=None):
    """Return a _list_ of applicable issues for the given game and milestone
        repo: github.Repository object
        milestone: github.Milestone object
        keep_labels: set of labels an issue must partake to, to be included
          in the results - by default all labels including no labels at all
        skip_labels: set of labels to skip, by default empty - if an issue
         has labels in this set it will be skipped
            Keep/skip Labels example:
                skip_labels = {"git"}
                keep_labels = {"bug"}
                issue.labels = ['enhancement'] // skipped
                issue.labels = ['bug', 'git'] // skipped
                issue.labels = ['bug'] // kept
                issue.labels = [] // skipped
        state: open or closed - by default 'all'
       return: a list of issues
        :rtype: :class:`github.PaginatedList.PaginatedList` of
        :class:`github.Issue.Issue`
    TODO: add sort, direction as needed, list comprehensions
    """
    current = _IssueCache.hit(repo, milestone, state)
    if not keep_labels and not skip_labels:  # no label filters, return All
        return current
    # return only issues that partake in keep_labels, and not in skip_labels
    result = []
    if not keep_labels and skip_labels:
        for issue in current:
            labels = set(x.name for x in issue.labels)
            if not skip_labels & labels:
                result.append(issue)
        return result
    elif keep_labels and skip_labels:
        keep_labels = keep_labels - skip_labels
        for issue in current:
            labels = set(x.name for x in issue.labels)
            if keep_labels & labels and not skip_labels & labels:
                result.append(issue)
        return result
    else:
        for issue in current:
            labels = set(x.name for x in issue.labels)
            if keep_labels & labels:
                result.append(issue)
        return result

def getUnlabeledIssues(repo, milestone=None, state=DEFAULT_ISSUE_STATE):
    return getIssues(repo, milestone, state=state,
                     skip_labels=_IssueCache.allLabels(repo))

def getClosedIssues(repo, milestone, keep_labels={'bug', 'enhancement'},
                    skip_labels=set()): # TODO move to globals.py
    """Return a list of closed issues for the given milestone
        repo: github.Repository object
        milestone: github.Milestone object
        keep_labels: set of labels for result to partake
       return:
        issue fixed in this milestone."""
    return getIssues(repo, milestone, keep_labels=keep_labels,
                     skip_labels=skip_labels,
                     state='closed')

def getGithub(*user):
    return github.Github(*user)

def getUserName(git):
    try:
        return git.get_user().name
    except github.BadCredentialsException as e:
        raise GithubApiException(e.message)

def allLabels(repo):
    return _IssueCache.allLabels(repo)

class GithubApiException(Exception):
    def __init__(self, message):
        # Call the base class constructor with the parameters it needs
        Exception.__init__(self, message)
        self.message = message
