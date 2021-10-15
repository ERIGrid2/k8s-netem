# FROM vtt/netem
FROM python:3.9-bullseye

RUN apt-get update && \
    apt-get -y install \
        nftables

COPY requirements.txt .
RUN pip install -r requirements.txt

RUN mkdir /src
WORKDIR /src
COPY . /src
RUN pip install -e .

CMD ["k8s-netem-sidecar"]
