from constants import RoomType, SpecialAgent
from model.dbModel.gtRoom import GtRoom
from model.dbModel.gtTeam import GtTeam
from service.roomService.chatRoom import ChatRoom


def test_operator_can_post_to_group_entry_without_explicit_operator_member():
    team = GtTeam(id=1, name="team")
    room = GtRoom(id=2, team_id=1, name="entry", type=RoomType.GROUP, agent_ids=[10, 11])
    chat_room = ChatRoom(team, room)
    assert chat_room.can_post_message(int(SpecialAgent.OPERATOR.value))


def test_operator_still_requires_membership_in_private_room():
    team = GtTeam(id=1, name="team")
    room = GtRoom(id=2, team_id=1, name="private", type=RoomType.PRIVATE, agent_ids=[10, 11])
    chat_room = ChatRoom(team, room)
    assert not chat_room.can_post_message(int(SpecialAgent.OPERATOR.value))
