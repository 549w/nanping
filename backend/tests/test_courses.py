"""课程端点测试。

覆盖 GET /courses 和 GET /courses/{course_id} 的正常与异常路径。
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
    async def test_search_multiple_params_and_logic(self, client, test_course, test_course2):
        """多字段搜索应使用 AND 逻辑，只返回同时满足所有条件的课程。"""
        # 搜索 test_course 的 code + name，应该能找到
        response = await client.get(
            "/courses",
            params={"code": test_course.code, "name": test_course.name},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        for item in data["items"]:
            assert item["code"] == test_course.code
            assert test_course.name in item["name"]

        # 搜索 test_course 的 code + 不存在的 name，应该返回空
        response = await client.get(
            "/courses",
            params={"code": test_course.code, "name": "不存在的课程名"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["items"] == []

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


class TestGetCourseDetail:
    """GET /courses/{course_id} 测试。"""

    @pytest.mark.asyncio
    async def test_basic_detail(self, client, test_course):
        """应返回课程基本信息。"""
        response = await client.get(f"/courses/{test_course.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_course.id
        assert data["code"] == "00010"
        assert data["name"] == "测试课程"
        assert data["teacher"] == "张三"
        assert data["department"] == "计算机系"
        assert data["credits"] == 3.0

    @pytest.mark.asyncio
    async def test_not_found(self, client):
        """不存在的 course_id 应返回 404。"""
        response = await client.get("/courses/99999")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_with_offerings(self, client, test_course, test_offering):
        """有开课记录时应返回 semesters 列表，学期应转为短格式并按降序排列。"""
        response = await client.get(f"/courses/{test_course.id}")
        assert response.status_code == 200
        data = response.json()
        semesters = data["semesters"]
        assert len(semesters) == 2
        # 短格式降序："2025春" > "2024秋"
        assert semesters[0]["semester"] == "2025春"
        assert semesters[0]["major"] == "软件工程"
        assert semesters[1]["semester"] == "2024秋"
        assert semesters[1]["major"] == "计算机科学与技术"

    @pytest.mark.asyncio
    async def test_no_offerings(self, client, test_course):
        """无开课记录时 semesters 应为空列表。"""
        response = await client.get(f"/courses/{test_course.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["semesters"] == []

    @pytest.mark.asyncio
    async def test_with_reviews(self, client, test_course, test_review, test_review_anonymous):
        """应正确计算 avg_rating 和 review_count，忽略已删除评价。"""
        response = await client.get(f"/courses/{test_course.id}")
        assert response.status_code == 200
        data = response.json()
        # test_review rating=4, test_review_anonymous rating=5 → avg=4.5
        assert data["review_count"] == 2
        assert data["avg_rating"] == 4.5

    @pytest.mark.asyncio
    async def test_deleted_reviews_excluded(self, client, test_course, test_review, test_review_deleted):
        """已删除评价不应计入 review_count 和 avg_rating。"""
        response = await client.get(f"/courses/{test_course.id}")
        assert response.status_code == 200
        data = response.json()
        # 只有 test_review (rating=4) 计入
        assert data["review_count"] == 1
        assert data["avg_rating"] == 4.0

    @pytest.mark.asyncio
    async def test_no_reviews(self, client, test_course):
        """无评价时 avg_rating 应为 null，review_count 应为 0。"""
        response = await client.get(f"/courses/{test_course.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["avg_rating"] is None
        assert data["review_count"] == 0
