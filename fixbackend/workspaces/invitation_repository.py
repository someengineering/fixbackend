from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Annotated, Optional, Sequence
from fastapi import Depends

from sqlalchemy import select
from fixbackend.auth.user_repository import UserRepository
from fixbackend.dependencies import FixDependency, ServiceNames

from fixbackend.ids import InvitationId, WorkspaceId
from fixbackend.types import AsyncSessionMaker
from fixbackend.workspaces.models import WorkspaceInvite
from fixbackend.workspaces.models import orm
from fixbackend.workspaces.repository import WorkspaceRepository
from fixcloudutils.util import utc


class InvitationRepository(ABC):
    @abstractmethod
    async def create_invitation(self, workspace_id: WorkspaceId, email: str) -> WorkspaceInvite:
        """Create an invite for a workspace."""
        raise NotImplementedError

    @abstractmethod
    async def get_invitation(self, invitation_id: InvitationId) -> Optional[WorkspaceInvite]:
        """Get an invitation by ID."""
        raise NotImplementedError

    @abstractmethod
    async def list_invitations(self, workspace_id: WorkspaceId) -> Sequence[WorkspaceInvite]:
        """List all invitations for a workspace."""
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
    ) -> None:
        self.session_maker = session_maker
        self.workspace_repository = workspace_repository

    async def create_invitation(self, workspace_id: WorkspaceId, email: str) -> WorkspaceInvite:
        async with self.session_maker() as session:
            user_repository = UserRepository(session)

            workspace = await self.workspace_repository.get_workspace(workspace_id, session=session)
            if workspace is None:
                raise ValueError(f"Workspace {workspace_id} does not exist.")

            user = await user_repository.get_by_email(email)

            if user:
                if user.id in workspace.all_users():
                    raise ValueError(f"User {user.id} is already a member of workspace {workspace_id}")

            invite = orm.OrganizationInvite(
                organization_id=workspace_id,
                user_id=user.id if user else None,
                user_email=email,
                expires_at=utc() + timedelta(days=7),
            )
            session.add(invite)
            await session.commit()
            await session.refresh(invite)
            return invite.to_model()

    async def get_invitation(self, invitation_id: InvitationId) -> Optional[WorkspaceInvite]:
        async with self.session_maker() as session:
            statement = select(orm.OrganizationInvite).where(orm.OrganizationInvite.id == invitation_id)
            results = await session.execute(statement)
            invite = results.unique().scalar_one_or_none()
            return invite.to_model() if invite else None

    async def list_invitations(self, workspace_id: WorkspaceId) -> Sequence[WorkspaceInvite]:
        async with self.session_maker() as session:
            statement = select(orm.OrganizationInvite).where(orm.OrganizationInvite.organization_id == workspace_id)
            results = await session.execute(statement)
            invites = results.scalars().all()
            return [invite.to_model() for invite in invites]

    async def delete_invitation(self, invitation_id: InvitationId) -> None:
        async with self.session_maker() as session:
            invite = await session.get(orm.OrganizationInvite, invitation_id)
            if invite is None:
                raise ValueError(f"Invitation {invitation_id} does not exist.")
            await session.delete(invite)
            await session.commit()


async def get_workspace_repository(fix: FixDependency) -> InvitationRepository:
    return fix.service(ServiceNames.invitation_repository, InvitationRepositoryImpl)


InvitationRepositoryDependency = Annotated[InvitationRepository, Depends(get_workspace_repository)]
