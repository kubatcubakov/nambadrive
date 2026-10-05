FROM eclipse-temurin:17-jre-jammy@sha256:8993f1aed8b25fcea7a7047a7949c1866fa558fc6830d938c22c4f13b26be9d7
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/* \
    && mkdir /opt/tika \
    && curl --fail --location --silent --show-error https://downloads.apache.org/tika/3.3.2/tika-server-standard-3.3.2.jar -o /opt/tika/server.jar \
    && echo 'fb1f2fe57ac458b09d44d41d816f582e1d2fc93488acff6275caf414d8d5ef94e42166edc0b488dc2fb6ef3aa21fab62b107c43b9060385ff6d675e393c2c9e9  /opt/tika/server.jar' | sha512sum -c -
USER 10001
ENTRYPOINT ["java", "-Xmx1024m", "-jar", "/opt/tika/server.jar", "--host", "0.0.0.0", "--port", "9998"]
