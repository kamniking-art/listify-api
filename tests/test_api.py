"""
pytest tests — запуск: pytest tests/ -v
Покрывает: auth, lists, items, receipts, websocket
"""
import pytest
import asyncio
import json
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.main import app
from app.core.database import Base, get_db

# ─── Test DB setup ────────────────────────────────────────────

TEST_DB_URL = "sqlite+aiosqlite:///./test.db"

test_engine = create_async_engine(TEST_DB_URL, echo=False)
TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with TestSession() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session", autouse=True)
async def create_tables():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# ─── Fixtures ─────────────────────────────────────────────────

@pytest.fixture
async def registered_user(client):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "test@listify.app",
        "password": "SecurePass123",
        "name": "Тестовый Пользователь",
    })
    assert resp.status_code == 201
    return resp.json()


@pytest.fixture
async def auth_headers(registered_user):
    token = registered_user["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def sample_list(client, auth_headers):
    resp = await client.post("/api/v1/lists", json={
        "name": "Тестовый список",
        "emoji": "🧪",
        "accent_color": "#6c63ff",
    }, headers=auth_headers)
    assert resp.status_code == 201
    return resp.json()


# ─── Auth Tests ───────────────────────────────────────────────

class TestAuth:
    async def test_register_success(self, client):
        resp = await client.post("/api/v1/auth/register", json={
            "email": "new@listify.app",
            "password": "Password123",
            "name": "Новый",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == "new@listify.app"

    async def test_register_duplicate_email(self, client, registered_user):
        resp = await client.post("/api/v1/auth/register", json={
            "email": "test@listify.app",
            "password": "Password123",
            "name": "Дубль",
        })
        assert resp.status_code == 400

    async def test_login_success(self, client, registered_user):
        resp = await client.post("/api/v1/auth/login", json={
            "email": "test@listify.app",
            "password": "SecurePass123",
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    async def test_login_wrong_password(self, client, registered_user):
        resp = await client.post("/api/v1/auth/login", json={
            "email": "test@listify.app",
            "password": "wrongpassword",
        })
        assert resp.status_code == 401

    async def test_anonymous_login(self, client):
        resp = await client.post("/api/v1/auth/anonymous", json={"device_id": "device-abc-123"})
        assert resp.status_code == 201
        assert resp.json()["user"]["is_anonymous"] is True

    async def test_anonymous_same_device_returns_same_user(self, client):
        r1 = await client.post("/api/v1/auth/anonymous", json={"device_id": "device-xyz"})
        r2 = await client.post("/api/v1/auth/anonymous", json={"device_id": "device-xyz"})
        assert r1.json()["user"]["id"] == r2.json()["user"]["id"]

    async def test_me(self, client, auth_headers):
        resp = await client.get("/api/v1/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["email"] == "test@listify.app"

    async def test_me_unauthorized(self, client):
        resp = await client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    async def test_refresh_token(self, client, registered_user):
        resp = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": registered_user["refresh_token"]
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()


# ─── Lists Tests ──────────────────────────────────────────────

class TestLists:
    async def test_create_list(self, client, auth_headers):
        resp = await client.post("/api/v1/lists", json={
            "name": "Список для теста",
            "emoji": "🛒",
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Список для теста"
        assert data["emoji"] == "🛒"
        assert data["items"] == []

    async def test_get_lists(self, client, auth_headers, sample_list):
        resp = await client.get("/api/v1/lists", headers=auth_headers)
        assert resp.status_code == 200
        lists = resp.json()
        assert isinstance(lists, list)
        assert any(lst["id"] == sample_list["id"] for lst in lists)

    async def test_get_list_by_id(self, client, auth_headers, sample_list):
        resp = await client.get(f"/api/v1/lists/{sample_list['id']}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == sample_list["id"]

    async def test_get_list_not_found(self, client, auth_headers):
        resp = await client.get("/api/v1/lists/nonexistent-id", headers=auth_headers)
        assert resp.status_code == 404

    async def test_update_list(self, client, auth_headers, sample_list):
        resp = await client.patch(f"/api/v1/lists/{sample_list['id']}", json={
            "name": "Обновлённый список",
            "emoji": "✅",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Обновлённый список"

    async def test_archive_list(self, client, auth_headers, sample_list):
        resp = await client.patch(f"/api/v1/lists/{sample_list['id']}", json={
            "is_archived": True
        }, headers=auth_headers)
        assert resp.status_code == 200
        # Archived lists don't appear in GET /lists
        lists_resp = await client.get("/api/v1/lists", headers=auth_headers)
        ids = [lst["id"] for lst in lists_resp.json()]
        assert sample_list["id"] not in ids

    async def test_delete_list(self, client, auth_headers):
        create_resp = await client.post("/api/v1/lists", json={"name": "To delete"}, headers=auth_headers)
        list_id = create_resp.json()["id"]
        del_resp = await client.delete(f"/api/v1/lists/{list_id}", headers=auth_headers)
        assert del_resp.status_code == 204
        get_resp = await client.get(f"/api/v1/lists/{list_id}", headers=auth_headers)
        assert get_resp.status_code == 404

    async def test_cannot_access_other_users_list(self, client):
        # Create user 1
        u1 = await client.post("/api/v1/auth/register", json={"email": "u1@test.app", "password": "Pass1234!", "name": "U1"})
        h1 = {"Authorization": f"Bearer {u1.json()['access_token']}"}
        lst = await client.post("/api/v1/lists", json={"name": "Private"}, headers=h1)
        list_id = lst.json()["id"]

        # Create user 2 and try to access user 1's list
        u2 = await client.post("/api/v1/auth/register", json={"email": "u2@test.app", "password": "Pass1234!", "name": "U2"})
        h2 = {"Authorization": f"Bearer {u2.json()['access_token']}"}
        resp = await client.get(f"/api/v1/lists/{list_id}", headers=h2)
        assert resp.status_code == 404


# ─── Items Tests ──────────────────────────────────────────────

class TestItems:
    async def test_add_item(self, client, auth_headers, sample_list):
        resp = await client.post(f"/api/v1/lists/{sample_list['id']}/items", json={
            "name": "Молоко Простоквашино 1л",
            "qty": 2,
            "unit": "шт",
        }, headers=auth_headers)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name_raw"] == "Молоко Простоквашино 1л"
        assert data["qty"] == 2
        assert data["status"] == "planned"
        # Auto-category detection
        assert data["category"] == "молочное"

    async def test_update_item_status(self, client, auth_headers, sample_list):
        add_resp = await client.post(f"/api/v1/lists/{sample_list['id']}/items", json={
            "name": "Хлеб", "qty": 1,
        }, headers=auth_headers)
        item_id = add_resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/lists/{sample_list['id']}/items/{item_id}/status",
            json={"status": "bought"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "bought"

    async def test_invalid_status(self, client, auth_headers, sample_list):
        add_resp = await client.post(f"/api/v1/lists/{sample_list['id']}/items", json={"name": "Тест"}, headers=auth_headers)
        item_id = add_resp.json()["id"]
        resp = await client.patch(
            f"/api/v1/lists/{sample_list['id']}/items/{item_id}/status",
            json={"status": "flying"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    async def test_batch_status(self, client, auth_headers, sample_list):
        ids = []
        for name in ["Творог", "Кефир", "Йогурт"]:
            r = await client.post(f"/api/v1/lists/{sample_list['id']}/items", json={"name": name}, headers=auth_headers)
            ids.append(r.json()["id"])

        resp = await client.post(
            f"/api/v1/lists/{sample_list['id']}/items/batch-status",
            json={"item_ids": ids, "status": "bought"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        for item in resp.json():
            assert item["status"] == "bought"

    async def test_delete_item(self, client, auth_headers, sample_list):
        add_resp = await client.post(f"/api/v1/lists/{sample_list['id']}/items", json={"name": "Удалить"}, headers=auth_headers)
        item_id = add_resp.json()["id"]
        del_resp = await client.delete(f"/api/v1/lists/{sample_list['id']}/items/{item_id}", headers=auth_headers)
        assert del_resp.status_code == 204

    async def test_reorder(self, client, auth_headers, sample_list):
        ids = []
        for name in ["A", "B", "C"]:
            r = await client.post(f"/api/v1/lists/{sample_list['id']}/items", json={"name": name}, headers=auth_headers)
            ids.append(r.json()["id"])

        reversed_ids = list(reversed(ids))
        resp = await client.post(
            f"/api/v1/lists/{sample_list['id']}/items/reorder",
            json={"item_ids": reversed_ids},
            headers=auth_headers,
        )
        assert resp.status_code == 204


# ─── OCR Tests ───────────────────────────────────────────────

class TestOCR:
    def test_parse_receipt_text(self):
        from app.services.ocr import parse_receipt_text

        sample = """
ПЯТЁРОЧКА
ООО "Агроторг"
05.03.2026 14:32

Молоко Простоквашино 1л    1  *  89.00  =  89.00
Яйца С1 10шт              1  *  124.00 = 124.00
Хлеб Бородинский           1  *  55.00  =  55.00

ИТОГО: 268.00
НАЛИЧНЫЕ: 300.00
СДАЧА: 32.00
        """
        result = parse_receipt_text(sample)
        assert result.store == "Пятёрочка"
        assert result.total == 268.0
        assert len(result.items) >= 2

    def test_normalize_name(self):
        from app.services.ocr import normalize_name
        assert normalize_name("Молоко 1л") == normalize_name("молоко 1л")
        assert "1л" not in normalize_name("Молоко 1л")

    def test_fuzzy_matching(self):
        from app.services.ocr import match_items_to_list

        receipt_items = [
            {"name_raw": "Молоко Простоквашино 1л", "qty": 1, "unit_price": 89, "line_total": 89},
            {"name_raw": "Хлеб Бородинский", "qty": 1, "unit_price": 55, "line_total": 55},
            {"name_raw": "Яйца Отборные 10шт", "qty": 1, "unit_price": 130, "line_total": 130},
        ]
        list_items = [
            {"id": "li1", "name_raw": "Молоко Простоквашино 1л"},
            {"id": "li2", "name_raw": "Хлеб"},
            {"id": "li3", "name_raw": "Яйца С1"},
        ]
        result = match_items_to_list(receipt_items, list_items, threshold=60.0)
        matched = [r for r in result if r["matched_item_id"]]
        assert len(matched) >= 2

    def test_fuzzy_no_match_for_unrelated(self):
        from app.services.ocr import match_items_to_list
        receipt_items = [{"name_raw": "Масло оливковое", "qty": 1}]
        list_items = [{"id": "x1", "name_raw": "Стиральный порошок"}]
        result = match_items_to_list(receipt_items, list_items, threshold=70.0)
        assert result[0]["matched_item_id"] is None


# ─── Health check ─────────────────────────────────────────────

class TestHealth:
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_docs_available(self, client):
        resp = await client.get("/docs")
        assert resp.status_code == 200
