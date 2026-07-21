"""games uuid unique per player

The baseline made games.uuid globally unique, but the same game uuid exists in
BOTH players' archives when two tracked players played each other. Uniqueness
must be per (player_id, uuid).

Revision ID: bbc799a88736
Revises: 5c6babe9b843
Create Date: 2026-07-20 19:44:40.463626

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'bbc799a88736'
down_revision: Union[str, None] = '5c6babe9b843'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# lets batch mode address SQLite's unnamed inline UNIQUE(uuid) so it can be dropped
NAMING = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def upgrade() -> None:
    with op.batch_alter_table('games', naming_convention=NAMING) as batch_op:
        batch_op.drop_constraint('uq_games_uuid', type_='unique')
        batch_op.create_unique_constraint('uq_games_player_uuid', ['player_id', 'uuid'])


def downgrade() -> None:
    with op.batch_alter_table('games', naming_convention=NAMING) as batch_op:
        batch_op.drop_constraint('uq_games_player_uuid', type_='unique')
        batch_op.create_unique_constraint('uq_games_uuid', ['uuid'])
