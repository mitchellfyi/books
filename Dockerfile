FROM python:3.13-alpine AS build

WORKDIR /site
COPY . .
RUN python bookflow build

FROM nginx:1.27-alpine

COPY --from=build /site/dist/ /usr/share/nginx/html/
EXPOSE 80
