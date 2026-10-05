FROM eclipse-temurin:17-jre-jammy@sha256:8993f1aed8b25fcea7a7047a7949c1866fa558fc6830d938c22c4f13b26be9d7
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends curl ca-certificates unzip && rm -rf /var/lib/apt/lists/* \
    && mkdir /opt/tika \
    && curl --fail --location --silent --show-error https://downloads.apache.org/tika/4.1.0/tika-server-standard-4.1.0.zip -o /tmp/tika.zip \
    && echo 'c932f84c569fb02df4f72ab060d6f2cf77b6797417040202401bc256e18a8f6f0ebc25d12d6dce222cb9328abfcb388cfa6511d7382c765a45687240a8a4bd7e  /tmp/tika.zip' | sha512sum -c - \
    && unzip -q /tmp/tika.zip -d /opt/tika && rm /tmp/tika.zip
COPY config.json /opt/tika/config.json
USER 10001
ENTRYPOINT ["java", "-Xmx1024m", "-jar", "/opt/tika/tika-server-standard-4.1.0.jar", "--config", "/opt/tika/config.json", "--host", "0.0.0.0", "--port", "9998"]
