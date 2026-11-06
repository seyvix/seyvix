# Build context: repository root (see /.dockerignore).
#
# Targets:
#   build  compile the SPA (build/client)
#   dev    Vite dev server; ./web is bind-mounted over /app
#   (last) caddy: static SPA + /api reverse proxy + automatic HTTPS

ARG NODE_IMAGE=node:22-alpine
ARG CADDY_IMAGE=caddy:2-alpine

FROM ${NODE_IMAGE} AS deps
WORKDIR /app
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund

FROM deps AS dev
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]

FROM deps AS build
COPY web/ ./
RUN npm run build && test -f build/client/index.html

FROM ${CADDY_IMAGE} AS caddy
COPY web/Caddyfile /etc/caddy/Caddyfile
RUN SITE_ADDRESS=:80 caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile \
    && addgroup -S -g 10001 caddy \
    && adduser -S -D -H -u 10001 -G caddy caddy \
    && chown -R caddy:caddy /data /config
COPY --from=build /app/build/client /srv
USER caddy
EXPOSE 80 443 443/udp
