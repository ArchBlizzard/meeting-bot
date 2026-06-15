import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models import Base, Meeting, SeenEmail


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
    def test_meeting_saved_with_id(self, db):
        m = Meeting(id="abc-defg-hij")
        db.add(m)
        db.commit()

        result = db.query(Meeting).filter(Meeting.id == "abc-defg-hij").first()
        assert result is not None
        assert result.id == "abc-defg-hij"
        assert result.digest is None
        assert result.created_at is not None

    def test_digest_cached_and_retrieved(self, db):
        m = Meeting(id="test-2")
        db.add(m)
        db.commit()

        digest = {"summary": "short", "action_items": [], "decisions": []}
        m.digest = json.dumps(digest)
        db.commit()

        result = db.query(Meeting).filter(Meeting.id == "test-2").first()
        assert result.digest is not None
        assert json.loads(result.digest)["summary"] == "short"

    def test_digest_updated_in_place(self, db):
        m = Meeting(id="test-3", digest=json.dumps({"summary": "v1", "action_items": [], "decisions": []}))
        db.add(m)
        db.commit()

        m.digest = json.dumps({"summary": "v2", "action_items": ["x"], "decisions": []})
        db.commit()

        result = db.query(Meeting).filter(Meeting.id == "test-3").first()
        assert json.loads(result.digest)["summary"] == "v2"


class TestSeenEmailModel:
    def test_seen_email_saved(self, db):
        e = SeenEmail(email_id="msg-abc-123")
        db.add(e)
        db.commit()

        result = db.query(SeenEmail).filter(SeenEmail.email_id == "msg-abc-123").first()
        assert result is not None
        assert result.seen_at is not None

    def test_no_duplicate_seen_emails(self, db):
        db.add(SeenEmail(email_id="msg-dup"))
        db.commit()

        from sqlalchemy.exc import IntegrityError
        db.add(SeenEmail(email_id="msg-dup"))
        with pytest.raises(IntegrityError):
            db.commit()

    def test_multiple_emails_tracked(self, db):
        for i in range(5):
            db.add(SeenEmail(email_id=f"msg-{i}"))
        db.commit()

        count = db.query(SeenEmail).count()
        assert count == 5
