import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="cura-te-ipsum",
    version="0.0.1.dev7",
    author="Maks Snegov",
    author_email="snegov@spqr.link",
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
            "cura-te-ipsum = curateipsum.main:main",
        ],
    },
    python_requires=">=3.6",
)
