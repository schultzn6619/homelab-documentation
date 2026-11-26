# Upstream Immich postgres image (the digest Immich v3.4.2 pins), with only the
# Debian packages that have critical CVEs fixed upgraded. PostgreSQL itself and
# its extensions (vchord 0.4.3, pgvector 0.8.1) are not touched.
# Remove this build and go back to the upstream image once Immich ships a rebuilt one.
FROM ghcr.io/immich-app/postgres:14-vectorchord0.4.3-pgvectors0.2.0@sha256:bcf63357191b76a916ae5eb93464d65c07511da41e3bf7a8416db519b40b1c23
RUN apt-get update \
 && apt-get install -y --only-upgrade --no-install-recommends \
      perl perl-base perl-modules-5.36 libperl5.36 \
      openssl libssl3 libgnutls30 \
 && rm -rf /var/lib/apt/lists/*
