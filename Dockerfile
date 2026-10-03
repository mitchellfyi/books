FROM python:3.13-alpine AS build

WORKDIR /site
COPY . .
ARG NEXT_PUBLIC_SENTRY_DSN
ARG NEXT_PUBLIC_OPS_PROJECT_ID
ARG NEXT_PUBLIC_SENTRY_RELEASE
ENV NEXT_PUBLIC_SENTRY_DSN=$NEXT_PUBLIC_SENTRY_DSN
ENV NEXT_PUBLIC_OPS_PROJECT_ID=$NEXT_PUBLIC_OPS_PROJECT_ID
ENV NEXT_PUBLIC_SENTRY_RELEASE=$NEXT_PUBLIC_SENTRY_RELEASE
RUN python bookflow build

# nginx 1.30 is the supported stable line; 1.27-alpine stopped receiving
# rebuilds in April 2025.
FROM nginx:1.30-alpine

COPY --from=build /site/dist/ /usr/share/nginx/html/
EXPOSE 80
