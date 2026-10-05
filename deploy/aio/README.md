# AIO

Complete single-host production/pilot service definitions, with one SeaweedFS master/volume and independent external backup. No HA. Use `compose.yml`, a private host-specific `.env`, TLS and mounted secrets. See [common deployment preflight](../common/README.md) before startup; the earlier HTTP-only Phase 1 example is superseded. CI does not deploy this profile. Real Authentik/live editor and representative capacity acceptance remain pending.
