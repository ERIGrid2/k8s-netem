FROM vtt/netem

COPY run.py /

CMD [ 'python3', '/run.py' ]
