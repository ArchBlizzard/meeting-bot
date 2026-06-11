import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, Meeting


@pytest.fixture
def db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path}/test.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestMeetingModel:
    def test_meeting_saved_with_all_fields(self, db):
        m = Meeting(
            id="test-1",
            url="https://meet.google.com/abc",
            email=None,
            status="complete",
        )
        m.transcript = "Alice: hi"
        db.add(m)
        db.commit()

        result = db.query(Meeting).filter(Meeting.id == "test-1").first()
        assert result is not None
        assert result.url == "https://meet.google.com/abc"
        assert result.status == "complete"
        assert result.transcript == "Alice: hi"
        assert result.created_at is not None

    def test_digest_cached_and_retrieved(self, db):
        m = Meeting(id="test-2", url="https://meet.google.com/abc", status="complete")
        m.transcript = "Alice: hi"
        db.add(m)
        db.commit()

        # Cache a digest
        digest = {"summary": "short", "action_items": [], "decisions": []}
        m.digest = json.dumps(digest)
        db.commit()

        result = db.query(Meeting).filter(Meeting.id == "test-2").first()
        assert result.digest is not None
        assert json.loads(result.digest)["summary"] == "short"

    def test_status_transitions(self, db):
        m = Meeting(id="test-3", url="https://meet.google.com/abc", status="pending")
        db.add(m)
        db.commit()

        m.status = "joining"
        db.commit()
        assert db.query(Meeting).filter(Meeting.id == "test-3").first().status == "joining"

        m.status = "complete"
        db.commit()
        assert db.query(Meeting).filter(Meeting.id == "test-3").first().status == "complete"

    def test_email_flow_saved_correctly(self, db):
        m = Meeting(id="test-4", email="bot@centralagent.ai", status="pending")
        db.add(m)
        db.commit()

        result = db.query(Meeting).filter(Meeting.id == "test-4").first()
        assert result.email == "bot@centralagent.ai"
        assert result.url is None
