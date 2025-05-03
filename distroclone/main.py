# Copyright 2024 R. Kent James
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This file generates an input to vcstool that represents all of the repositories
# in a rosdistro.

import argparse
from io import StringIO
import logging
import os
import shutil
import sys
import yaml

logging.basicConfig(format='[%(name)s] [%(levelname)s] %(message)s', level=logging.INFO)
logger = logging.getLogger('distroclone')

from catkin_pkg.packages import find_packages_allowing_duplicates
from rosdistro import get_index
from rosdistro import get_index_url
from rosdistro import get_distribution_cache_string
from vcstool.commands.import_ import main as import_main
from vcstool.commands.pull import main as pull_main


def main(args=None):
    parser = get_parser()
    config = parser.parse_args(args)
    logger.info(f'Cloning distro {config.distro} to path {config.path}')

    output_dir = config.path
    os.makedirs(output_dir, exist_ok=True)

    index = get_index(get_index_url())
    if config.distro == 'github':
        repositories = get_local_repositories(config)
    else:
        repositories = get_extended_distribution_cache(index, config, logger=logger)
    existing_directories = os.listdir(output_dir)
    if '_release' in existing_directories:
        existing_directories.remove('_release')
    for name in existing_directories:
        if name not in repositories:
            directory = os.path.join(output_dir, name)
            logger.info(f'Did not find {directory}, removing')
            shutil.rmtree(directory, ignore_errors=False)

    vcs_repos = {'repositories': {}}
    for key, repo in repositories.items():
        clone_repo = repo.get('source', repo.get('doc'))
        if clone_repo:
            vcs_repos['repositories'][key] = clone_repo

    logger.info(f'Cloning {len(vcs_repos["repositories"])} repositories')
    sys.stdin = StringIO(yaml.dump(vcs_repos))
    import_main(['--force', output_dir])
    logger.info('pulling changes into repos')
    pull_main([output_dir])

    # Locate any missing packages
    logger.info(f'Locating and cloning from release_repository any missing packages')
    packages = find_packages_allowing_duplicates(output_dir, exclude_paths=[os.path.join(output_dir, '_release')])
    packages_set = set()
    for package in packages.values():
        packages_set.add(package.name)

    vcs_repos = {'repositories': {}}
    output_dir_release = os.path.join(config.path, '_release')
    os.makedirs(output_dir_release, exist_ok=True)
    existing_directories = os.listdir(output_dir_release)

    for key, repo in repositories.items():
        release = repo.get('release')
        if release and 'packages' in release:
            for package_name in release['packages']:
                if package_name not in packages_set:
                    logger.warning(f'Did not find {package_name}, adding to reclone list')
                    vcs_repos['repositories'][package_name] = {
                        'type': 'git',
                        'url': release['url'],
                        'version': f'release/{config.distro}/{package_name}'
                    }
                    packages_set.add(package_name)
    if vcs_repos['repositories']:
        logger.info(f'Recloning {len(vcs_repos["repositories"])} packages')
        sys.stdin = StringIO(yaml.dump(vcs_repos))
        import_main(['--force', '--repos', output_dir_release])
        pull_main(['--repos', output_dir_release])
    else:
        logger.info('No missing packages found')

    # delete any packages that are not in current release
    for package_name in existing_directories:
        if package_name not in packages_set:
            logger.info(f'Did not find {package_name}, removing')
            directory = os.path.join(output_dir_release, package_name)
            shutil.rmtree(directory, ignore_errors=False)


def get_parser():
    parser = argparse.ArgumentParser(
        prog='distroclone',
        description='Clone a full rosdistro.',
    )
    parser.add_argument('-d', '--distro', help='ros distro name (ie rolling)', default='rolling')
    parser.add_argument('-p', '--path', help='path to output repos to', default='rosdistro')
    parser.add_argument('-c', '--config_file', help='config file name (config.yaml)', default=None)
    parser.add_argument('-m', '--max-repos', type=int, help='Maximum repos to clone, -1 for no limit', default=-1)

    '''
    Example config.yaml:

launch_ros:
  source:
    type: git
    url: https://github.com/rkent/launch_ros.git
    version: fix-rosdoc2

    '''
    return parser

def merge(a: dict, b: dict, path=[], logger=None):
    """Deep merge dict b into dict a (in place)

    with: inner1 = {'i1': 11, 'i2': 12, 'i3': 13}
    inner2 = {'i1': 21, 'i2': 12, 'i4': 24}
    outer1 = {'a': inner1, 'c': {'cc'}}
    outer2 = {'a': inner2, 'b': 2}
    merge(outer1, outer2)
    print(outer1)

    result is:
    {'a': {'i1': 21, 'i2': 12, 'i3': 13, 'i4': 24}, 'c': {'cc'}, 'b': 2}
    """
    # Adapted from
    # https://stackoverflow.com/questions/7204805/deep-merge-dictionaries-of-dictionaries-in-python/7205107#7205107
    for key in b:
        if key in a:
            if isinstance(a[key], dict) and isinstance(b[key], dict):
                merge(a[key], b[key], path + [str(key)])
            elif type(a[key]) == type(b[key]):
                a[key] = b[key]
            else:
                conflict = '.'.join(path + [str(key)]) + f': {a[key]} vs {b[key]}'
                if logger:
                    logger.warning(f'Dictionary merge conflict at {conflict}')
                else:
                    raise RuntimeError('Merge conflict at ' + conflict)
        else:
            a[key] = b[key]
    return a


def read_cfg_file(fname):
    try:
        with open(fname) as f:
            return yaml.safe_load(f.read())
    except (IOError, KeyError, yaml.YAMLError):
        return None

def get_local_repositories(config):
    print(f'Current working directory is {os.getcwd()}')
    local_path = os.path.join('github', 'distribution.yaml')
    with open(local_path, 'r') as f:
        data = yaml.safe_load(f)
    print(data.keys())
    repositories = data['repositories']

    # Limit length of repositories, mostly a debug features
    if config and config.max_repos >= 0:
        if logger:
            logger.info(f'Limiting cloned repos count to {config.max_repos}')
        limited_repositories = {}
        count = 0

        for key in repositories.keys():
            limited_repositories[key] = repositories[key]
            count += 1
            if count >= config.max_repos:
                break
        repositories = limited_repositories

    return repositories

def get_extended_distribution_cache(index, config, logger=None):
    yaml_str = get_distribution_cache_string(index, config.distro)
    data = yaml.safe_load(yaml_str)
    repositories= data['distribution_file'][0]['repositories']
    repoMerge = None

    # allow config to modify values of repositories
    if config and config.config_file:
        repoMerge = read_cfg_file(config.config_file)
        if not repoMerge:
            if logger:
                logger.warning(f'Could not find repo merge file <{config.config_file}>')
            else:
                raise RuntimeError(f'Could not find repo merge file {config.config_file}')
        if repoMerge:
            logger.info(f'Merging repos {list(repoMerge.keys())}')
            merge(repositories, repoMerge, logger=logger)

    # Limit length of repositories, mostly a debug features
    if config and config.max_repos >= 0:
        if logger:
            logger.info(f'Limiting cloned repos count to {config.max_repos}')
        limited_repositories = {}
        count = 0
        # Always start with any merged repos
        keys = (list(repoMerge.keys()) if repoMerge else []) + list(repositories.keys())

        for key in keys:
            limited_repositories[key] = repositories[key]
            count += 1
            if count >= config.max_repos:
                break
        repositories = limited_repositories

    return repositories

if __name__ == '__main__':
    main()
