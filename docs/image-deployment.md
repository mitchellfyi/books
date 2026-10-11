# Image deployment

GitHub Actions runs the strict tooling tests, library validation and site build
for each revision. The production workflow waits for that revision's successful
`verify.yml` push run, then builds a private AMD64 GHCR image and asks Control to
deploy its immutable digest. Control verifies the provider receipt and public HTTPS
before completing the deployment.

The workflow receives only public build settings through GitHub OIDC. The
existing error reporter and Umami website ID are retained. `app/app.js` is copied
without compilation or minification, so its source is already the served code;
this project does not produce private source maps. Runtime credentials and local
environment files are excluded from the build context.

The initial image is published with `CONTROL_IMAGE_DEPLOY_ENABLED` (or the older
`OPS_IMAGE_DEPLOY_ENABLED`) unset. Conversion of the existing Coolify application
follows Control's image deployment runbook after checking its domain, storage and
runtime settings. Set `CONTROL_IMAGE_DEPLOY_ENABLED` to `true` only after the audited provider conversion and read-back pass. Manual
`publish_only=true` builds never deploy.

The library and committed audio remain part of the image. This workflow does
not generate narration or change the content-processing schedule.
