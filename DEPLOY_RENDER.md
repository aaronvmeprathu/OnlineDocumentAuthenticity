# Render Deployment

This project is ready to deploy as a public Flask app on Render.

## Quick Steps

1. Push this project to GitHub.
2. In Render, create a new Web Service from the repository.
3. Render can detect `render.yaml` automatically.
4. After the first deploy, open the public Render URL and register a new document so the generated QR code uses the public domain.

## Important Storage Note

This app writes uploaded files, document hashes, and QR images to `STORAGE_ROOT`.

The Render config sets:

```text
STORAGE_ROOT=/opt/render/project/src/storage
```

For public testing, that works immediately.

For persistent real-world use, add a persistent disk in Render and mount it at:

```text
/opt/render/project/src/storage
```

Without a disk, uploaded data can be lost whenever the service is rebuilt or restarted.

## Optional Custom Domain

If you later connect your own domain, you can set:

```text
PUBLIC_BASE_URL=https://your-domain.example
```

That makes future QR codes point to your custom domain instead of the default Render domain.
