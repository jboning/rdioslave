from setuptools import setup, find_packages
setup(
    name = "rdioslave",
    version = "0.1",
    packages = find_packages(),
    entry_points = {
        'console_scripts' : [
            "rdioslave = rdioslave.__main__:main",
        ]
    },

    # These are the versions originally developed against
    install_requires = [
        "requests >= 1.2.3",
        "six >= 1.3.0",
        "tornado >= 3.0.1",
    ],

    author = "Josiah Boning",
    author_email = "jboning@gmail.com",
    description = "Interfaceless Rdio client for use with Remote Control Mode",
    license = "BSD 2-clause",
    keywords = "Rdio client player",
    url = "https://github.com/jboning/rdioslave",
)
