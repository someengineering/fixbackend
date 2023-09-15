# Build Container to create a wheel and export requirements.txt file
FROM python:3.11 as build-stage
WORKDIR /app
ADD . /app
RUN pip install poetry && poetry build && poetry export -f requirements.txt -o dist/requirements.txt


# Create final image by installing the wheel with all requirements
FROM python:3.11-slim as final-stage
WORKDIR /app
COPY --from=build-stage /app/dist /app/dist
RUN  apt-get update \
      && apt-get -y --no-install-recommends install apt-utils dumb-init \
      && pip install --no-cache-dir -r dist/requirements.txt \
      && pip install --no-cache-dir --no-deps dist/*.whl  \
      && rm -rf /app/dist
ADD fixbackend/templates /app/fixbackend/templates
# migrations needs to run too
ADD migrations /app/migrations
ADD alembic.ini /app/alembic.ini
EXPOSE 8000
ENTRYPOINT ["/bin/dumb-init", "--", "fixbackend"]
