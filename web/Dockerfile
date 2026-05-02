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

FROM nginx:1.27-alpine AS production

COPY web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
