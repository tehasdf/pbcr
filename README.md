# PBCR - a basic container runtime written in Python

This allows running container images fetched from OCI registries (currently: only the docker registry).

To use this, install the package using pip, and run:
```bash
pbcr run docker.io/library/hello-world -n hello-world-container
````

Copying files into containers is also possible, see [the nginx example](examples/nginx/run.sh)

## WARNING

This is just an experimental toy project, I made to learn about container runtimes and OCI registries.
**DO NOT USE THIS FOR ANY SERIOUS PURPOSE**

## Missing bits

Currently, pbcr doesn't implement:
- mounting (only copying)
- any kind of layered FS (always untars the image layers)
- network namespaces
