# PROD-COMPACT

Run app.compose.yml on app+Office, data.compose.yml on data/master03, storage01.compose.yml on master01/volume01/filer/S3, storage02.compose.yml on master02/volume02. Separate independent backup target. Per-host private environment/certificates are mandatory. Three-master quorum and replication 001 retain identical application/schema. See [common deployment preflight](../common/README.md); do not treat Docker bridges as a cross-host network.
