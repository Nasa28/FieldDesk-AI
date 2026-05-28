# Node 22 because corepack pulls pnpm 11.2.2+ which needs the
# node:sqlite built-in (added in Node 22.5). Node 20 ERR_UNKNOWN_BUILTIN_MODULEs
# on the pnpm bootstrap.
FROM node:22-alpine AS deps
RUN corepack enable
WORKDIR /app
# Docker Desktop's bridge network has been flaky on big tarballs (sharp,
# typescript): pnpm defaults to a 60s fetch timeout which trips on slow
# downloads. 5min timeout + 5 retries gives transient hiccups room to
# recover without killing the whole image build.
ENV npm_config_fetch_timeout=300000 \
    npm_config_fetch_retries=5 \
    npm_config_fetch_retry_mintimeout=10000 \
    npm_config_fetch_retry_maxtimeout=120000
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile --filter fielddesk-web...

FROM node:22-alpine AS build
RUN corepack enable
WORKDIR /app
# NEXT_PUBLIC_API_URL is baked into the client bundle at build time, not
# resolved at runtime. Pass it as a build arg from docker-compose so the
# image reflects whichever host port the API is exposed on (default 8080,
# override via .env when running side-by-side with other dev stacks).
ARG NEXT_PUBLIC_API_URL=http://localhost:8080
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/apps/web/node_modules ./apps/web/node_modules
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web ./apps/web
RUN pnpm --filter fielddesk-web build

FROM node:22-alpine AS runtime
RUN corepack enable
ENV NODE_ENV=production
WORKDIR /app
COPY --from=build /app ./
EXPOSE 3000
CMD ["pnpm", "--filter", "fielddesk-web", "start"]
