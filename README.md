# FIX backend

Backend for fix. Contains user auth module and provides API for the SPA. 

## Installation 

### Devcontainers

Open in vscode, click run devcontainer and the project will be installed automagically.

### Local setup

1. Install Poetry
2. Install MariaDB
3. Run `poetry install` in the project folder


## Configuration

You need obtain google oauth credentials. See the instructions here: https://developers.google.com/identity/protocols/oauth2

Then make them available under `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` env vars.

## Run the service

Run `potery run start` to run the service. Swagger docs are available at http://127.0.0.1:8000/docs