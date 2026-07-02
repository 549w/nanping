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


class TestMatchCourses:
    """POST /courses/match 测试。"""

    @pytest.mark.asyncio
    async def test_exact_code_match(self, client, test_course, test_review):
        """课程号精确匹配 + 教师重叠 → match_level='code'，含评价。"""
        response = await client.post(
            "/courses/match",
            json={
                "queries": [
                    {"code": "00010", "teacher": "张三", "name": "测试课程"}
                ]
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 1
        result = data["results"][0]
        assert result["query_index"] == 0
        assert len(result["matched"]) >= 1
        first = result["matched"][0]
        assert first["match_level"] == "code"
        assert first["course"]["code"] == "00010"
        assert first["course"]["teacher"] == "张三"
        assert first["course"]["review_count"] == 1
        assert len(first["top_reviews"]) >= 1

    @pytest.mark.asyncio
    async def test_code_match_different_teacher(self, client, test_course, test_review):
        """课程号匹配但教师不同 → 仍返回 code 级别匹配。"""
        response = await client.post(
            "/courses/match",
            json={
                "queries": [
                    {"code": "00010", "teacher": "王五", "name": "测试课程"}
                ]
            },
        )
        assert response.status_code == 200
        data = response.json()
        result = data["results"][0]
        assert len(result["matched"]) >= 1
        assert result["matched"][0]["match_level"] == "code"

    @pytest.mark.asyncio
    async def test_teacher_fallback(self, client, test_course, test_review):
        """课程号无匹配 → 回退到教师搜索 → match_level='teacher'。"""
        response = await client.post(
            "/courses/match",
            json={
                "queries": [
                    {"code": "99999", "teacher": "张三", "name": "任意名称"}
                ]
            },
        )
        assert response.status_code == 200
        data = response.json()
        result = data["results"][0]
        assert len(result["matched"]) >= 1
        assert result["matched"][0]["match_level"] == "teacher"
        assert result["matched"][0]["course"]["teacher"] == "张三"

    @pytest.mark.asyncio
    async def test_no_match(self, client):
        """课程号和教师都匹配不到 → 返回空列表。"""
        response = await client.post(
            "/courses/match",
            json={
                "queries": [
                    {"code": "99999", "teacher": "不存在", "name": "不存在的课"}
                ]
            },
        )
        assert response.status_code == 200
        data = response.json()
        result = data["results"][0]
        assert result["matched"] == []

    @pytest.mark.asyncio
    async def test_multiple_queries(self, client, test_course, test_review):
        """多条查询各自独立返回结果。"""
        response = await client.post(
            "/courses/match",
            json={
                "queries": [
                    {"code": "00010", "teacher": "张三", "name": "测试课程"},
                    {"code": "99999", "teacher": "不存在", "name": "不存在的课"},
                ]
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 2
        assert len(data["results"][0]["matched"]) >= 1  # 命中
        assert data["results"][1]["matched"] == []  # 未命中

    @pytest.mark.asyncio
    async def test_empty_queries(self, client):
        """空查询列表应正常返回。"""
        response = await client.post(
            "/courses/match",
            json={"queries": []},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_code_match_no_reviews_fallback_to_teacher(
        self, client, db_session, test_course2, test_course, test_review
    ):
        """课程号匹配到的课程无评价 → 回退教师搜索 → 找到有评价的课程。"""
        # test_course2: code="00020", teacher="李四", 无评价
        # test_course:  code="00010", teacher="张三", 有评价
        # 查询 code="00020"（无评价课程）+ teacher="张三"（有评价课程的老师）
        # → 按 code 搜到 test_course2 但无评价
        # → 回退按 teacher 搜到 test_course
        response = await client.post(
            "/courses/match",
            json={
                "queries": [
                    {"code": "00020", "teacher": "张三", "name": "另一门课"}
                ]
            },
        )
        assert response.status_code == 200
        data = response.json()
        result = data["results"][0]
        # 应该通过教师回退找到 test_course
        assert len(result["matched"]) >= 1
        assert result["matched"][0]["match_level"] == "teacher"
        assert result["matched"][0]["course"]["code"] == "00010"

    @pytest.mark.asyncio
    async def test_anonymous_review_email_null(
        self, client, test_course, test_review, test_review_anonymous
    ):
        """匿名评价的 user_email 应为 null。"""
        response = await client.post(
            "/courses/match",
            json={
                "queries": [
                    {"code": "00010", "teacher": "张三", "name": "测试课程"}
                ]
            },
        )
        assert response.status_code == 200
        data = response.json()
        reviews = data["results"][0]["matched"][0]["top_reviews"]
        emails = [r["user_email"] for r in reviews]
        # 至少有一条匿名评价，其 user_email 为 null
        assert None in emails

    @pytest.mark.asyncio
    async def test_deleted_review_not_included(
        self, client, test_course, test_review, test_review_deleted
    ):
        """已删除评价不应出现在 top_reviews 中。"""
        response = await client.post(
            "/courses/match",
            json={
                "queries": [
                    {"code": "00010", "teacher": "张三", "name": "测试课程"}
                ]
            },
        )
        assert response.status_code == 200
        data = response.json()
        reviews = data["results"][0]["matched"][0]["top_reviews"]
        contents = [r["content"] for r in reviews]
        assert "已删除的评价" not in contents
