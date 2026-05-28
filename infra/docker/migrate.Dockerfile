# Pull goose from its GitHub release rather than ghcr.io/pressly/goose,
# which started requiring registry auth even for anonymous public pulls.
# A 5MB static binary in a slim base avoids the auth dance for anyone
# who clones the repo and wants `docker compose up` to just work.
FROM alpine:3.20

# Pin the version so re-pulls don't silently shift schema-migration behavior.
# Bump deliberately; goose has shipped breaking flag changes in past majors.
ARG GOOSE_VERSION=v3.22.1

RUN apk add --no-cache curl ca-certificates \
    && ARCH=$(uname -m) \
    && case "$ARCH" in \
         x86_64)  GOARCH=x86_64 ;; \
         aarch64) GOARCH=arm64 ;; \
         *) echo "unsupported arch: $ARCH" && exit 1 ;; \
       esac \
    && curl -fsSL -o /usr/local/bin/goose \
        "https://github.com/pressly/goose/releases/download/${GOOSE_VERSION}/goose_linux_${GOARCH}" \
    && chmod +x /usr/local/bin/goose

ENTRYPOINT ["/usr/local/bin/goose"]
