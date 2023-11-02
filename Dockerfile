# Build Container to create a wheel and export requirements.txt file
FROM python:3.11 as build-stage
WORKDIR /app
ADD . /app

RUN mkdir dist

ENV POETRY_HOME="/opt/poetry" \
    POETRY_VERSION=1.6.1

ENV PATH="$POETRY_HOME/bin:$PATH"

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -

RUN poetry export -f requirements.txt -o dist/requirements.txt

# Create final image by installing the wheel with all requirements
FROM python:3.11-slim as final-stage
WORKDIR /app
COPY --from=build-stage /app /app

ENV POETRY_HOME="/opt/poetry"

ENV PATH="$POETRY_HOME/bin:$PATH"

# copy already installed poetry
COPY --from=build-stage $POETRY_HOME $POETRY_HOME

# install dumb-init and requirements which do not change often
RUN  apt-get update \
      && apt-get -y --no-install-recommends install apt-utils dumb-init \
      && pip install --no-cache-dir -r dist/requirements.txt

# build wheels in the end to not invalidate cache
RUN poetry build
# install the wheels and cleanup
RUN pip install --no-cache-dir --no-deps dist/*.whl  \
      && rm -rf /app/* \
      && rm -rf $POETRY_HOME
# migrations needs to run too
ADD migrations /app/migrations
ADD alembic.ini /app/alembic.ini
ADD static /app/static
EXPOSE 8000
ENTRYPOINT ["/bin/dumb-init", "--", "fixbackend"]
