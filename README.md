# nfweb
nfweb is a minimal web front-end for nextflow written in python and flask

![screenshot of nfweb](https://i.imgur.com/n9jXoh9.png)

# Prerequisites
    apt install tree coreutils python3 python3-pip python3-bcrypt python3-passlib
    pip3 install Flask Flask-Login

# Install and run
    git clone https://github.com/dvolk/nfweb
    cd nfweb
    FLASK_APP=nfweb.py flask run

# Configure
nfweb is configured by editing config.yaml

If using ldap to authenticate, the user running nfweb will need to be able to run /bin/chown with sudo without a password. This is achieved by putting a line such as

    denisv@ndm.local ALL=(ALL) NOPASSWD: /bin/chown

in `/etc/sudoers`. This allows it change the file permissions to that of the authenticated user.
