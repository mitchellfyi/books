# Error tracking

Production browser exceptions go to the Control-hosted GlitchTip
service at https://errors.m12n.org. Keep Umami for traffic analytics.

Control provisions the project and supplies `NEXT_PUBLIC_SENTRY_DSN`, `NEXT_PUBLIC_CONTROL_PROJECT_ID` and `NEXT_PUBLIC_SENTRY_RELEASE`.
The build reads the project ID from `NEXT_PUBLIC_CONTROL_PROJECT_ID` first and falls back to the older `NEXT_PUBLIC_OPS_PROJECT_ID`,
and loads the reporter from `https://errors.m12n.org/static/control-errors.v1.js`.
Use the existing DSN for every domain alias; never create a second project for
an alias or copy another application's key. The release is the deployment's
immutable Git SHA. Provisioning a DSN alone does not instrument an application.

Use `window.OpsErrors.captureException(error)` for unexpected caught exceptions. Do not
report expected validation, authorization or not-found results. Automatic
reporting must remain enabled in the shared layout and applicable runtimes.

The before-send filters remove user details, cookies, request bodies, headers,
query strings and breadcrumbs. Do not attach customer content, prompts, files,
provider responses or secrets. Tracing and session replay are disabled.
Administrative API tokens and source-map upload credentials must never enter
HTML, public environment variables, build arguments or committed files.

From this project's Errors section in Control, choose **View errors**. Control owners
use the native OIDC login; no shared administrative password is placed in the
link. After a deployment, trigger a harmless uniquely named exception and
confirm its project, hostname, release and stack in GlitchTip. Refresh Control
metrics and check that the count changed. Do not add a public crash endpoint.
