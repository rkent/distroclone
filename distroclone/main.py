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
import os
import sys
import yaml

from catkin_pkg.packages import find_packages_allowing_duplicates
from rosdistro import get_index
from rosdistro import get_distribution_cache
from vcstool.commands.import_ import main as import_main


INDEX_URL = 'https://raw.githubusercontent.com/ros/rosdistro/master/index-v4.yaml'


def main(args=None):
    parser = get_parser()
    config = parser.parse_args(args)

    output_dir = os.path.join(config.path, config.distro)
    os.makedirs(output_dir, exist_ok=True)

    index = get_index(INDEX_URL)
    dist_cache = get_distribution_cache(index, config.distro)
    dist_file = dist_cache.distribution_file
    repositories = dist_file.repositories

    vcs_repos = {'repositories': {}}
    for repo in repositories.values():
        source = repo.source_repository
        release = repo.release_repository
        doc = repo.doc_repository
        if source:
            clone_repo = source
        elif doc:
            clone_repo = doc
        else:
            clone_repo = None
        if clone_repo:
            vcs_repos['repositories'][clone_repo.name] = {
                'type': clone_repo.type,
                'url': clone_repo.url,
                'version': clone_repo.version
            }

    # print(vcs_repos)
    # sys.stdin = StringIO(yaml.dump(vcs_repos))
    # import_main([output_dir])

    # Locate any missing packages
    release_packages_path = os.path.join(output_dir, 'release_packages')
    subfolders = [ f.path for f in os.scandir(output_dir) if f.is_dir() ]
    # print(subfolders)
    packages = find_packages_allowing_duplicates(output_dir)
    packages_set = set()
    vcs_repos = {'repositories': {}}
    output_dir_release = os.path.join(config.path, config.distro + '-release')
    os.makedirs(output_dir_release, exist_ok=True)
    for package in packages.values():
        packages_set.add(package.name)
    for repo in repositories.values():
        release = repo.release_repository
        if not release:
            continue
        for package_name in release.package_names:
            if not package_name in packages_set:
                print(f'Did not find {package_name}')
                # print(release.type, release.url, release.version)
                vcs_repos['repositories'][release.name] = {
                    'type': release.type,
                    'url': release.url,
                    'version': f'release/{config.distro}/{package_name}'
                }
    if vcs_repos['repositories']:
        print(vcs_repos)
        sys.stdin = StringIO(yaml.dump(vcs_repos))
        import_main([output_dir_release])


    #print(packages_set)


def get_parser():
    parser = argparse.ArgumentParser(
        prog='distroclone',
        description='Clone a full rosdistro',
    )
    parser.add_argument('-d', '--distro', help='ros distro name (ie rolling)', default='rolling')
    parser.add_argument('-p', '--path', help='path to output repos to', default='rosdistro')
    return parser

if __name__ == '__main__':
    main()