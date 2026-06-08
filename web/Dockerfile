FROM node:22-alpine AS base

WORKDIR /app

FROM base AS production-base

ENV NODE_ENV=production
ENV HOST=0.0.0.0
ENV PORT=80

COPY web/package.json web/package-lock.json ./
RUN npm ci --omit=dev

EXPOSE 80

CMD ["npm", "run", "start"]

FROM production-base AS production-prebuilt

COPY web/build ./build
COPY web/server.js ./server.js

FROM base AS dependencies

COPY web/package.json web/package-lock.json ./
RUN npm ci

FROM dependencies AS development

COPY web/ ./

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM dependencies AS build

ENV VITE_BUILD_MINIFY=false

COPY web/ ./
RUN npm run build

FROM production-base AS production

COPY --from=build /app/build ./build
COPY web/server.js ./server.js
