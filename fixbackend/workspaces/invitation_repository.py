from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Annotated, Callable, Optional, Sequence

from fastapi import Depends
from fixcloudutils.util import utc
from sqlalchemy import select
from sqlalchemy.orm.exc import StaleDataError

from fixbackend.auth.user_repository import UserRepository
from fixbackend.dependencies import FixDependency, ServiceNames
from fixbackend.errors import ResourceNotFound, WrongState
from fixbackend.ids import InvitationId, WorkspaceId
from fixbackend.types import AsyncSessionMaker
from fixbackend.workspaces.models import WorkspaceInvitation, orm
from fixbackend.workspaces.repository import WorkspaceRepository

from logging import getLogger

log = getLogger(__name__)


class InvitationRepository(ABC):
    @abstractmethod
    async def create_invitation(self, workspace_id: WorkspaceId, email: str) -> WorkspaceInvitation:
        """Create an invite for a workspace."""
        raise NotImplementedError

    @abstractmethod
    async def get_invitation(self, invitation_id: InvitationId) -> Optional[WorkspaceInvitation]:
        """Get an invitation by ID."""
        raise NotImplementedError

    @abstractmethod
    async def get_invitation_by_email(self, email: str) -> Optional[WorkspaceInvitation]:
        """Get an invitation by email."""
        raise NotImplementedError

    @abstractmethod
    async def list_invitations(self, workspace_id: WorkspaceId) -> Sequence[WorkspaceInvitation]:
        """List all invitations for a workspace."""
        raise NotImplementedError

    @abstractmethod
    async def update_invitation(
        self,
        invitation_id: InvitationId,
        update_fn: Callable[[WorkspaceInvitation], WorkspaceInvitation],
    ) -> WorkspaceInvitation:
        """Update an invitation."""
        raise NotImplementedError

    @abstractmethod
    async def delete_invitation(self, invitation_id: InvitationId) -> None:
        """Delete an invitation."""
        raise NotImplementedError


class InvitationRepositoryImpl(InvitationRepository):
    def __init__(
        self,
        session_maker: AsyncSessionMaker,
        workspace_repository: WorkspaceRepository,
        user_repository: UserRepository,
    ) -> None:
        self.session_maker = session_maker
        self.workspace_repository = workspace_repository
        self.user_repository = user_repository

    async def create_invitation(self, workspace_id: WorkspaceId, email: str) -> WorkspaceInvitation:
        async with self.session_maker() as session:
            existing_invitation = (
                await session.execute(
                    select(orm.OrganizationInvite)
                    .where(orm.OrganizationInvite.organization_id == workspace_id)
                    .where(orm.OrganizationInvite.user_email == email)
                )
            ).scalar_one_or_none()
            if existing_invitation:
                return existing_invitation.to_model()

            workspace = await self.workspace_repository.get_workspace(workspace_id, session=session)
            if workspace is None:
                raise ResourceNotFound(f"Workspace {workspace_id} does not exist.")

            user = await self.user_repository.get_by_email(email, session=session)

            if user:
                if user.id in workspace.all_users():
                    raise WrongState(f"User {user.id} is already a member of workspace {workspace_id}")

            invite = orm.OrganizationInvite(
                organization_id=workspace_id,
                user_email=email,
                expires_at=utc() + timedelta(days=7),
            )
            session.add(invite)
            await session.commit()
            await session.refresh(invite)
            return invite.to_model()

    async def get_invitation(self, invitation_id: InvitationId) -> Optional[WorkspaceInvitation]:
        async with self.session_maker() as session:
            statement = select(orm.OrganizationInvite).where(orm.OrganizationInvite.id == invitation_id)
            results = await session.execute(statement)
            invite = results.unique().scalar_one_or_none()
            return invite.to_model() if invite else None

    async def get_invitation_by_email(self, email: str) -> Optional[WorkspaceInvitation]:
        async with self.session_maker() as session:
            statement = select(orm.OrganizationInvite).where(orm.OrganizationInvite.user_email == email)
            results = await session.execute(statement)
            invite = results.unique().scalar_one_or_none()
            return invite.to_model() if invite else None

    async def list_invitations(self, workspace_id: WorkspaceId) -> Sequence[WorkspaceInvitation]:
        async with self.session_maker() as session:
            statement = select(orm.OrganizationInvite).where(orm.OrganizationInvite.organization_id == workspace_id)
            results = await session.execute(statement)
            invites = results.scalars().all()
            return [invite.to_model() for invite in invites]

    async def update_invitation(
        self,
        invitation_id: InvitationId,
        update_fn: Callable[[WorkspaceInvitation], WorkspaceInvitation],
    ) -> WorkspaceInvitation:
        async def do_updade() -> WorkspaceInvitation:
            async with self.session_maker() as session:
                stored_invite = await session.get(orm.OrganizationInvite, invitation_id)
                if stored_invite is None:
                    raise ResourceNotFound(f"Cloud account {invitation_id} not found")

                invite = update_fn(stored_invite.to_model())

                if stored_invite.to_model() == invite:
                    # nothing to update
                    return invite

                stored_invite.organization_id = invite.workspace_id
                stored_invite.user_email = invite.email
                stored_invite.expires_at = invite.expires_at
                stored_invite.accepted_at = invite.accepted_at

                await session.commit()
                await session.refresh(stored_invite)
                return stored_invite.to_model()

        while True:
            try:
                return await do_updade()
            except StaleDataError:  # in case of concurrent update
                pass

    async def delete_invitation(self, invitation_id: InvitationId) -> None:
        async with self.session_maker() as session:
            invite = await session.get(orm.OrganizationInvite, invitation_id)
            if invite is None:
                log.info(f"Invitation {invitation_id} does not exist, skipping deletion.")
                return None  # let's be idempotent
            await session.delete(invite)
            await session.commit()


async def get_invitation_repository(fix: FixDependency) -> InvitationRepository:
    return fix.service(ServiceNames.invitation_repository, InvitationRepositoryImpl)


InvitationRepositoryDependency = Annotated[InvitationRepository, Depends(get_invitation_repository)]
