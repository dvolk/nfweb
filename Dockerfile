FROM ubuntu:16.04

RUN apt update && apt install -y --no-install-recommends \
  python3 python3-pip python3-setuptools git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN pip3 install --upgrade pip 
RUN pip3 install Flask Flask-Login PyYaml

COPY . /nfweb
WORKDIR /nfweb
ENV FLASK_APP=nfweb.py
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8
ENTRYPOINT ["flask"]
CMD ["run","--host=0.0.0.0"]
