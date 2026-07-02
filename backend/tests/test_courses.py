"""课程端点测试。

覆盖 GET /courses 的正常与异常路径。
"""

import pytest


class TestSearchCourses:
    """GET /courses 测试。"""

    @pytest.mark.asyncio
    async def test_search_by_code(self, client, test_course):
        """按课程编号搜索应返回匹配课程。"""
        response = await client.get("/courses", params={"code": "00010"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        codes = [item["code"] for item in data["items"]]
        assert "00010" in codes

    @pytest.mark.asyncio
    async def test_search_by_name(self, client, test_course):
        """按课程名称搜索应返回匹配课程。"""
        response = await client.get("/courses", params={"name": "测试"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        names = [item["name"] for item in data["items"]]
        assert any("测试" in n for n in names)

    @pytest.mark.asyncio
    async def test_search_by_teacher(self, client, test_course):
        """按教师搜索应返回匹配课程。"""
        response = await client.get("/courses", params={"teacher": "张"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_search_no_params(self, client):
        """无任何搜索参数应返回 400。"""
        response = await client.get("/courses")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_search_no_results(self, client):
        """搜索不存在的课程应返回空列表。"""
        response = await client.get("/courses", params={"code": "99999999"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

    @pytest.mark.asyncio
    async def test_pagination(self, client, test_course):
        """分页参数应正确生效。"""
        response = await client.get(
            "/courses", params={"name": "测试", "page": 1, "page_size": 10}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10
        assert "total" in data
        assert len(data["items"]) <= 10

    @pytest.mark.asyncio
    async def test_avg_rating_and_review_count(self, client, test_course, test_review):
        """有评价的课程应返回正确的 avg_rating 和 review_count。"""
        response = await client.get("/courses", params={"code": test_course.code})
        assert response.status_code == 200
        data = response.json()
        item = data["items"][0]
        assert item["review_count"] == 1
        assert item["avg_rating"] == 4.0

    @pytest.mark.asyncio
    async def test_avg_rating_null_without_reviews(self, client, test_course2):
        """无评价的课程 avg_rating 应为 null，review_count 应为 0。"""
        response = await client.get("/courses", params={"code": test_course2.code})
        assert response.status_code == 200
        data = response.json()
        if data["items"]:
            item = data["items"][0]
            assert item["avg_rating"] is None
            assert item["review_count"] == 0
