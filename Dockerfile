FROM python:3.11-slime

ADD . /app
WORKDIR /app
RUN pip install poetry && poetry build && pip install dist/*.whl && rm -rf /app
ADD fixbackend/static /app/fixbackend/static

EXPOSE 8000
ENTRYPOINT ["fixbackend"]
