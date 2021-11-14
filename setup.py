import setuptools
import subprocess


def get_version_from_vcs():
    ret_code, git_ver = subprocess.getstatusoutput("git describe")
    if ret_code != 0:
        from curateipsum._version import version
        return version

    with open("curateipsum/_version.py", "w") as fd:
        fd.write("version = \"%s\"\n" % git_ver)
        return git_ver


with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="cura-te-ipsum",
    version=get_version_from_vcs(),
    author="Maks Snegov",
    author_email="snegov@spqr.link",
    url="https://github.com/snegov/cura-te-ipsum",
    description="Backup utility",
    long_description=long_description,
    long_description_content_type="text/markdown",
    project_urls={
        "Bug Tracker": "https://github.com/snegov/cura-te-ipsum/issues",
        "GitHub": "https://github.com/snegov/cura-te-ipsum",
    },
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Topic :: System :: Archiving :: Backup",
    ],
    packages=setuptools.find_packages(include=["curateipsum"]),
    entry_points={
        "console_scripts": [
            "cura-te-ipsum = curateipsum.cli:main",
        ],
    },
    python_requires=">=3.6",
)
