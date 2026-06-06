FROM node:22-alpine AS base

WORKDIR /app

FROM base AS dependencies

COPY web/package.json web/package-lock.json ./
RUN npm ci

FROM dependencies AS development

COPY web/ ./

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM dependencies AS build

COPY web/ ./
RUN npm run build

FROM node:22-alpine AS production

WORKDIR /app

ENV NODE_ENV=production
ENV HOST=0.0.0.0
ENV PORT=80

COPY web/package.json web/package-lock.json ./
RUN npm ci --omit=dev

COPY --from=build /app/build ./build
COPY web/server.js ./server.js

EXPOSE 80

CMD ["npm", "run", "start"]
