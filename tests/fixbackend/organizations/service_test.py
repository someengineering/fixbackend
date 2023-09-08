import asyncio
import uuid
from typing import AsyncIterator

import pytest
from alembic.command import upgrade as alembic_upgrade
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, AsyncEngine
from sqlalchemy_utils import create_database, database_exists, drop_database

from fixbackend.auth.db import get_user_db
from fixbackend.auth.models import User
from fixbackend.organizations.service import OrganizationService

DATABASE_URL = "mysql+aiomysql://root@127.0.0.1:3306/fixbackend-testdb"

# only used to create/drop the database
SYNC_DATABASE_URL = "mysql+pymysql://root@127.0.0.1:3306/fixbackend-testdb"


@pytest.fixture(scope="session")
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """
    Creates a new database for a test and runs the migrations.
    """
    # make sure the db exists and it is clean
    if database_exists(SYNC_DATABASE_URL):
        drop_database(SYNC_DATABASE_URL)
    else:
        create_database(SYNC_DATABASE_URL)

    while not database_exists(SYNC_DATABASE_URL):
        await asyncio.sleep(0.1)

    engine = create_async_engine(DATABASE_URL)
    alembic_config = AlembicConfig("alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", DATABASE_URL)
    await asyncio.to_thread(alembic_upgrade, alembic_config, "head")

    yield engine

    await engine.dispose()
    drop_database(SYNC_DATABASE_URL)


@pytest.fixture
async def session(db_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """
    Creates a new database session for a test, that is bound to the
    database transaction and rolled back after the test is done.

    Allows for running tests in parallel.
    """
    connection = db_engine.connect()
    await connection.start()
    transaction = connection.begin()
    await transaction.start()
    session = AsyncSession(bind=connection)

    yield session

    await session.close()
    await transaction.close()
    await connection.close()


@pytest.fixture
async def user(session: AsyncSession) -> User:
    user_db = await anext(get_user_db(session))
    user_dict = {
        "email": "foo@bar.com",
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }
    user = await user_db.create(user_dict)

    return user


@pytest.mark.asyncio
async def test_create_organization(session: AsyncSession, user: User) -> None:
    service = OrganizationService(session)
    organization = await service.create_organization(name="Test Organization", slug="test-organization", owner=user)

    assert organization.name == "Test Organization"
    assert organization.slug == "test-organization"
    for owner in organization.owners:
        assert owner.user == user

    assert len(organization.members) == 0

    # creating an organization with the same slug should raise an exception
    with pytest.raises(Exception):
        await service.create_organization(name="Test Organization", slug="test-organization", owner=user)


@pytest.mark.asyncio
async def test_get_organization(session: AsyncSession, user: User) -> None:
    # we can get an existing organization by id
    service = OrganizationService(session)
    organization = await service.create_organization(name="Test Organization", slug="test-organization", owner=user)

    retrieved_organization = await service.get_organization(organization.id)
    assert retrieved_organization == organization

    # if the organization does not exist, None should be returned
    retrieved_organization = await service.get_organization(uuid.uuid4())
    assert retrieved_organization is None


@pytest.mark.asyncio
async def test_list_organizations(session: AsyncSession, user: User) -> None:
    service = OrganizationService(session)
    organization = await service.create_organization(name="Test Organization", slug="test-organization", owner=user)

    # the user should be the owner of the organization
    organizations = await service.list_organizations(user.id)
    assert len(organizations) == 1
    assert organizations[0] == organization


@pytest.mark.asyncio
async def test_add_to_organization(session: AsyncSession, user: User) -> None:
    # add an existing user to the organization
    service = OrganizationService(session)
    organization = await service.create_organization(name="Test Organization", slug="test-organization", owner=user)
    org_id = organization.id

    user_db = await anext(get_user_db(session))
    new_user_dict = {"email": "bar@bar.com", "hashed_password": "notreallyhashed", "is_verified": True}
    new_user = await user_db.create(new_user_dict)
    new_user_id = new_user.id
    await service.add_to_organization(organization_id=org_id, user_id=new_user.id)

    retrieved_organization = await service.get_organization(org_id, with_users=True)
    assert retrieved_organization
    assert len(retrieved_organization.members) == 1
    assert next(iter(retrieved_organization.members)).user == new_user

    # when adding a user which is already a member of the organization, nothing should happen
    await service.add_to_organization(organization_id=org_id, user_id=new_user_id)

    # when adding a non-existing user to the organization, an exception should be raised
    with pytest.raises(Exception):
        await service.add_to_organization(organization_id=org_id, user_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_create_invitation(session: AsyncSession, user: User) -> None:
    # create an invitation for an existing user
    service = OrganizationService(session)
    organization = await service.create_organization(name="Test Organization", slug="test-organization", owner=user)
    org_id = organization.id

    user_db = await anext(get_user_db(session))
    user_dict = {
        "email": "123foo@bar.com",
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }
    new_user = await user_db.create(user_dict)
    new_user_id = new_user.id

    invitation = await service.create_invitation(organization_id=org_id, user_id=new_user.id)
    assert invitation.organization_id == org_id
    assert invitation.user_id == new_user_id


@pytest.mark.asyncio
async def test_accept_invitation(session: AsyncSession, user: User) -> None:
    service = OrganizationService(session)
    organization = await service.create_organization(name="Test Organization", slug="test-organization", owner=user)
    org_id = organization.id

    user_db = await anext(get_user_db(session))
    user_dict = {
        "email": "123foo@bar.com",
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }
    new_user = await user_db.create(user_dict)

    invitation = await service.create_invitation(organization_id=org_id, user_id=new_user.id)

    # accept the invitation
    await service.accept_invitation(invitation_id=invitation.id)

    retrieved_organization = await service.get_organization(org_id, with_users=True)
    assert retrieved_organization
    assert len(retrieved_organization.members) == 1
    assert next(iter(retrieved_organization.members)).user == new_user


@pytest.mark.asyncio
async def test_list_invitations(session: AsyncSession, user: User) -> None:
    service = OrganizationService(session)
    organization = await service.create_organization(name="Test Organization", slug="test-organization", owner=user)
    org_id = organization.id

    user_db = await anext(get_user_db(session))
    user_dict = {
        "email": "bar@bar.com",
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }
    new_user = await user_db.create(user_dict)

    invitation = await service.create_invitation(organization_id=org_id, user_id=new_user.id)

    # list the invitations
    invitations = await service.list_invitations(organization_id=org_id)
    assert len(invitations) == 1
    assert invitations[0] == invitation


@pytest.mark.asyncio
async def test_delete_invitation(session: AsyncSession, user: User) -> None:
    service = OrganizationService(session)
    organization = await service.create_organization(name="Test Organization", slug="test-organization", owner=user)
    org_id = organization.id

    user_db = await anext(get_user_db(session))
    user_dict = {
        "email": "bar@bar.com",
        "hashed_password": "notreallyhashed",
        "is_verified": True,
    }
    new_user = await user_db.create(user_dict)

    invitation = await service.create_invitation(organization_id=org_id, user_id=new_user.id)

    # delete the invitation
    await service.delete_invitation(invitation_id=invitation.id)

    # the invitation should not exist anymore
    invitations = await service.list_invitations(organization_id=org_id)
    assert len(invitations) == 0
