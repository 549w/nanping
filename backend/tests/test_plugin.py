"""插件统一接口测试。

覆盖 POST /plugin 的正常与异常路径，
确保新接口不影响现有 /courses/match 端点。
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient

from backend.app.models import ActivityLog, News


@pytest_asyncio.fixture
async def test_news(db_session):
    """创建一条测试公告。"""
    news = News(
        title="测试公告",
        content="这是一条测试公告内容",
        is_active=1,
        created_at="2025-06-01T00:00:00",
    )
    db_session.add(news)
    await db_session.commit()
    await db_session.refresh(news)
    return news


class TestPluginEndpoint:
    """POST /plugin 测试。"""

    @pytest.mark.asyncio
    async def test_basic_match(self, client: AsyncClient, test_course, test_review):
        """单个查询匹配到课程时应返回正确结果。"""
        response = await client.post(
            "/plugin",
            json={
                "queries": [
                    {"code": "00010", "teacher": "张三", "name": "测试课程"}
                ],
                "username": "测试用户",
                "gender": "men.png",
            },
        )
        assert response.status_code == 200
        data = response.json()

        # 验证顶层结构
        assert "toast" in data
        assert "news" in data
        assert "results" in data

        # 验证 toast
        assert data["toast"]["loading"] == "「南评」正在加载评论..."
        assert "匹配到 1 条评价" in data["toast"]["success"]
        assert data["toast"]["error"] == "加载失败，请检查网络连接"

        # 验证 news 是列表
        assert isinstance(data["news"], list)

        # 验证 results
        assert len(data["results"]) == 1
        result = data["results"][0]
        assert result["query_index"] == 0
        assert result["exact_course_id"] == test_course.id
        assert len(result["matched"]) >= 1
        assert result["matched"][0]["match_level"] == "code+teacher+name"
        course = result["matched"][0]["course"]
        assert course["code"] == "00010"
        assert course["name"] == "测试课程"
        assert course["avg_rating"] is not None
        assert course["review_count"] >= 1

    @pytest.mark.asyncio
    async def test_no_match(self, client: AsyncClient):
        """无匹配查询应返回空结果和相应的 toast 文案。"""
        response = await client.post(
            "/plugin",
            json={
                "queries": [
                    {"code": "99999", "teacher": "不存在", "name": "不存在的课"}
                ],
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "暂无匹配" in data["toast"]["success"]
        assert len(data["results"]) == 1
        assert data["results"][0]["matched"] == []

    @pytest.mark.asyncio
    async def test_multiple_queries(
        self, client: AsyncClient, test_course, test_course2, test_review
    ):
        """多条查询时 toast 应反映实际匹配数。"""
        response = await client.post(
            "/plugin",
            json={
                "queries": [
                    {"code": "00010", "teacher": "张三", "name": "测试课程"},
                    {"code": "00020", "teacher": "李四", "name": "另一门课"},
                ],
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "匹配到 1 条评价" in data["toast"]["success"]
        assert len(data["results"]) == 2

        # 第一个有匹配
        assert len(data["results"][0]["matched"]) >= 1
        # 第二个无评价，无匹配
        assert data["results"][1]["matched"] == []

    @pytest.mark.asyncio
    async def test_news_included(self, client: AsyncClient, test_news):
        """响应中应包含活跃公告。"""
        response = await client.post(
            "/plugin",
            json={
                "queries": [
                    {"code": "99999", "teacher": "x", "name": "x"}
                ],
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert len(data["news"]) >= 1
        news = data["news"][0]
        assert news["title"] == "测试公告"
        assert "测试公告内容" in news["content"]

    @pytest.mark.asyncio
    async def test_username_and_gender_optional(self, client: AsyncClient):
        """username 和 gender 均为可选字段。"""
        response = await client.post(
            "/plugin",
            json={
                "queries": [
                    {"code": "99999", "teacher": "x", "name": "x"}
                ],
            },
        )
        assert response.status_code == 200
        # 不应因为缺少可选字段而报错

    @pytest.mark.asyncio
    async def test_activity_logged(
        self, client: AsyncClient, db_session, test_course, test_review
    ):
        """POST /plugin 应写入活动日志。"""
        response = await client.post(
            "/plugin",
            json={
                "queries": [
                    {"code": "00010", "teacher": "张三", "name": "测试课程"}
                ],
                "username": "loguser",
                "gender": "women.png",
            },
        )
        assert response.status_code == 200
        await db_session.commit()  # 确保日志已写入

        # 查询最后一条 plugin_query 日志
        from sqlalchemy import select
        result = await db_session.execute(
            select(ActivityLog)
            .where(ActivityLog.action == "plugin_query")
            .order_by(ActivityLog.created_at.desc())
            .limit(1)
        )
        log = result.scalar_one_or_none()
        assert log is not None
        # details 是 JSON 字符串
        import json
        detail = json.loads(log.details)
        assert detail["query_count"] == 1
        assert detail["matched_count"] == 1
        assert detail["username"] == "loguser"
        assert detail["gender"] == "women.png"


class TestExistingEndpointsUnaffected:
    """确保新接口不影响现有端点。"""

    @pytest.mark.asyncio
    async def test_courses_match_still_works(
        self, client: AsyncClient, test_course, test_review
    ):
        """POST /courses/match 应如常工作，不含 toast/news 字段。"""
        response = await client.post(
            "/courses/match",
            json={
                "queries": [
                    {"code": "00010", "teacher": "张三", "name": "测试课程"}
                ],
                "username": "test",
            },
        )
        assert response.status_code == 200
        data = response.json()

        # 旧接口不应有 toast 和 news
        assert "toast" not in data
        assert "news" not in data
        # 但应有 results
        assert "results" in data
        assert len(data["results"]) == 1
        assert len(data["results"][0]["matched"]) >= 1

    @pytest.mark.asyncio
    async def test_news_still_works(self, client: AsyncClient, test_news):
        """GET /news 应如常工作。"""
        response = await client.get("/news", params={"limit": 2})
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["title"] == "测试公告"
