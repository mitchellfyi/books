FROM python:3.14-alpine@sha256:f6a589d43c42b9e7f7dc67a12d37132491f362859a5d750607710cc56da3bc72 AS build

WORKDIR /site
COPY . .
ARG NEXT_PUBLIC_SENTRY_DSN
ARG NEXT_PUBLIC_CONTROL_PROJECT_ID
ARG NEXT_PUBLIC_SENTRY_RELEASE
ENV NEXT_PUBLIC_SENTRY_DSN=$NEXT_PUBLIC_SENTRY_DSN
ENV NEXT_PUBLIC_CONTROL_PROJECT_ID=$NEXT_PUBLIC_CONTROL_PROJECT_ID
ENV NEXT_PUBLIC_SENTRY_RELEASE=$NEXT_PUBLIC_SENTRY_RELEASE
RUN python bookflow build

# nginx 1.30 is the supported stable line; 1.27-alpine stopped receiving
# rebuilds in April 2025. Dependabot refreshes the digest as the tag is
# rebuilt and stays off odd-numbered mainline releases (see dependabot.yml).
FROM nginx:1.30-alpine@sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94

COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /site/dist/ /usr/share/nginx/html/
EXPOSE 80
