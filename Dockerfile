FROM python:3.9-bullseye

RUN apt-get update && \
    apt-get -y install \
        nftables \
        python3-nftables \
        iproute2 \
        supervisor \
        iproute2

# Add python3-nftables to system path
ENV PYTHONPATH=/usr/lib/python3/dist-packages/

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY etc/supervisord.conf /etc/

RUN mkdir /src
WORKDIR /src
COPY . /src
RUN pip install -e .

CMD ["supervisord", "-c", "/etc/supervisord.conf"]
