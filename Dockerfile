# Build Container to create a wheel and export requirements.txt file
FROM python:3.11 as build-stage
WORKDIR /app
ADD . /app
RUN pip install poetry && poetry build && poetry export -f requirements.txt -o dist/requirements.txt


# Create final image by installing the wheel with all requirements
FROM python:3.11-slim as final-stage
WORKDIR /app
COPY --from=build-stage /app/dist /app/dist
RUN pip install --no-cache-dir -r dist/requirements.txt; pip install --no-cache-dir --no-deps dist/*.whl && rm -rf /app/dist
# static files are not included in the wheel and need to be copied manually
ADD fixbackend/static /app/fixbackend/static
# migrations needs to run too
ADD migrations /app/migrations
ADD alembic.ini /app/alembic.ini
EXPOSE 8000
ENTRYPOINT ["fixbackend", "--migrate"]
