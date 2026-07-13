from execution.alerts import send_discord_alert, _last_sent


def test_no_webhook_url_is_noop(monkeypatch):
    """ไม่ตั้งค่า DISCORD_WEBHOOK_URL — ต้องไม่ throw แค่คืน False เงียบๆ"""
    assert send_discord_alert("test", None) is False
    assert send_discord_alert("test", "") is False


def test_dedupe_blocks_repeat_within_window(monkeypatch):
    _last_sent.clear()
    calls = []

    def fake_post(url, json, timeout):
        calls.append(json)

        class Resp:
            status_code = 200

        return Resp()

    monkeypatch.setattr("requests.post", fake_post)

    ok1 = send_discord_alert("first", "http://fake.webhook", dedupe_key="k1", dedupe_seconds=999)
    ok2 = send_discord_alert("second (should be blocked)", "http://fake.webhook", dedupe_key="k1", dedupe_seconds=999)

    assert ok1 is True
    assert ok2 is False  # ถูก dedupe กันซ้ำ
    assert len(calls) == 1  # เรียก requests.post แค่ครั้งเดียว


def test_no_dedupe_key_always_sends(monkeypatch):
    _last_sent.clear()
    calls = []

    def fake_post(url, json, timeout):
        calls.append(json)

        class Resp:
            status_code = 200

        return Resp()

    monkeypatch.setattr("requests.post", fake_post)

    send_discord_alert("a", "http://fake.webhook", dedupe_key=None)
    send_discord_alert("b", "http://fake.webhook", dedupe_key=None)

    assert len(calls) == 2  # ไม่มี dedupe_key = ยิงทุกครั้งไม่กัน


def test_request_failure_does_not_raise(monkeypatch):
    def fake_post(*args, **kwargs):
        raise ConnectionError("network down")

    monkeypatch.setattr("requests.post", fake_post)

    # ต้องไม่ throw ออกมา แค่คืน False — alert พังต้องไม่ทำให้ trading loop หลักพังตาม
    result = send_discord_alert("test", "http://fake.webhook", dedupe_key=None)
    assert result is False
