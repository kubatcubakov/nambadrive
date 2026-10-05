FROM postgres:17.11-alpine@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24
RUN apk upgrade --no-cache && apk add --no-cache python3 su-exec && rm /usr/local/bin/gosu
COPY gosu /usr/local/bin/gosu
RUN chmod 755 /usr/local/bin/gosu && /usr/local/bin/gosu nobody sh -c 'test "$(id -u)" = 65534'
COPY wal.py /opt/nambadrive/wal.py
