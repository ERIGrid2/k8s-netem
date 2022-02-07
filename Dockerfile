# FROM vtt/netem
FROM python:3.9-bullseye

RUN apt-get update && \
    apt-get -y install \
        nftables \
        python3-nftables \
        iproute2 \
        supervisor \
        iproute2 \
        python3-requests \
        python3-tornado \
        python3-simplejson \
        python3-passlib \
        python3-netaddr \
        python3-websocket

# Add python3-nftables to system path
ENV PYTHONPATH=/usr/lib/python3/dist-packages/

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

RUN mkdir /src
WORKDIR /src
COPY . /src
RUN pip install -e .

# CMD ["k8s-netem-sidecar"]
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]