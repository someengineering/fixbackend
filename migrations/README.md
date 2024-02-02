# Migrations for fixbackend

A good intro: https://harrisonmorgan.dev/2021/02/15/getting-started-with-fastapi-users-and-alembic/

## Usage

### Update the database schema to the latest version

Just start the app, it will automatically run the migrations. Alternatively, you can run the following command from the root of the project:

`poetry run alembic upgrade head`

### Create a new migration

`poetry run alembic revision --autogenerate -m "your message"`

It will detect model changes and create 90% correct migration, but make sure to manually check the results for anomalies. 

If you see an empty migration, you probably forgot to import your new model class in `fixbackend/all_models.py`.