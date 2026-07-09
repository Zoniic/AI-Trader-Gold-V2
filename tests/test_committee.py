from core.committee import Committee, CommitteeMember


def _member(name: str, approve: bool, comment: str = "x") -> CommitteeMember:
    return CommitteeMember(name, "Tester", lambda ctx: (approve, comment))


def test_committee_approves_with_at_most_one_dissent():
    committee = Committee(
        [_member("a", True), _member("b", True), _member("c", True), _member("d", True), _member("e", False)]
    )
    approved, opinions = committee.review({})
    assert approved is True
    assert len(opinions) == 5
    assert sum(1 for o in opinions if o["approve"]) == 4


def test_committee_rejects_with_two_dissents():
    committee = Committee(
        [_member("a", True), _member("b", True), _member("c", True), _member("d", False), _member("e", False)]
    )
    approved, opinions = committee.review({})
    assert approved is False
    assert len(opinions) == 5


def test_opinions_carry_member_identity_and_comment():
    committee = Committee([_member("สมชาย", True, "เห็นด้วยเพราะ X")] * 1 + [_member(f"m{i}", True) for i in range(4)])
    approved, opinions = committee.review({})
    assert approved
    assert opinions[0]["member"] == "สมชาย"
    assert opinions[0]["comment"] == "เห็นด้วยเพราะ X"
    assert set(opinions[0].keys()) == {"member", "role", "approve", "comment"}
